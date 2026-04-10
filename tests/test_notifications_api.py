import json
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from edilcloud.modules.notifications.models import Notification
from edilcloud.modules.notifications.services import create_notification
from edilcloud.modules.projects.models import (
    Project,
    ProjectActivity,
    ProjectMember,
    ProjectMemberStatus,
    ProjectTask,
)
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceAccessRequest, WorkspaceRole
from edilcloud.modules.workspaces.services import (
    approve_workspace_access_request,
    create_workspace_access_request,
)


def auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"JWT {token}"}


def login_and_get_token(*, email: str, password: str) -> str:
    client = Client()
    response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": email,
                "password": password,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()["token"]


def create_workspace_user(*, workspace: Workspace, email: str, password: str, first_name: str, last_name: str, role: str):
    user = get_user_model().objects.create_user(
        email=email,
        password=password,
        username=email.split("@")[0],
        first_name=first_name,
        last_name=last_name,
        language="it",
    )
    profile = Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=role,
        first_name=first_name,
        last_name=last_name,
        language="it",
    )
    return user, profile


@pytest.mark.django_db
def test_notifications_center_lists_and_marks_reads():
    user_model = get_user_model()
    recipient_user = user_model.objects.create_user(
        email="recipient@example.com",
        password="devpass123",
        username="recipient",
        first_name="Paola",
        last_name="Verdi",
        language="it",
    )
    sender_user = user_model.objects.create_user(
        email="sender@example.com",
        password="devpass123",
        username="sender",
        first_name="Luca",
        last_name="Neri",
        language="it",
    )
    recipient_workspace = Workspace.objects.create(name="Ricezione Workspace")
    sender_workspace = Workspace.objects.create(name="Cantiere Mittente")
    recipient_profile = Profile.objects.create(
        workspace=recipient_workspace,
        user=recipient_user,
        email=recipient_user.email,
        role=WorkspaceRole.MANAGER,
        first_name="Paola",
        last_name="Verdi",
        language="it",
    )
    sender_profile = Profile.objects.create(
        workspace=sender_workspace,
        user=sender_user,
        email=sender_user.email,
        role=WorkspaceRole.OWNER,
        first_name="Luca",
        last_name="Neri",
        language="it",
        position="Direttore tecnico",
    )

    first = create_notification(
        recipient_profile=recipient_profile,
        sender_user=sender_user,
        sender_profile=sender_profile,
        subject="Nuovo aggiornamento task",
        body="E stata caricata una nuova relazione di cantiere.",
        kind="project.post.created",
        project_id=12,
        task_id=34,
        data={"project_id": 12, "task_id": 34},
    )
    second = create_notification(
        recipient_profile=recipient_profile,
        subject="Promemoria sicurezza",
        body="Verifica i DPI prima dell'accesso in area lavori.",
        kind="workspace.notice",
        data={"severity": "medium"},
    )

    token = login_and_get_token(email=recipient_user.email, password="devpass123")
    client = Client()

    center_response = client.get("/api/v1/notifications?limit=10", **auth_header(token))
    assert center_response.status_code == 200
    center_payload = center_response.json()
    assert center_payload["unread_count"] == 2
    assert [item["id"] for item in center_payload["results"]] == [second.id, first.id]
    assert center_payload["results"][1]["sender"]["company_name"] == sender_workspace.name

    mark_read_response = client.post(
        f"/api/v1/notifications/{first.id}/read",
        content_type="application/json",
        **auth_header(token),
    )
    assert mark_read_response.status_code == 200
    mark_read_payload = mark_read_response.json()
    assert mark_read_payload["id"] == first.id
    assert mark_read_payload["is_read"] is True
    assert mark_read_payload["read_at"] is not None

    mark_all_response = client.post(
        "/api/v1/notifications/read-all",
        content_type="application/json",
        **auth_header(token),
    )
    assert mark_all_response.status_code == 200
    assert mark_all_response.json()["updated"] == 1

    refreshed_response = client.get("/api/v1/notifications?limit=10", **auth_header(token))
    assert refreshed_response.status_code == 200
    refreshed_payload = refreshed_response.json()
    assert refreshed_payload["unread_count"] == 0
    assert all(item["is_read"] for item in refreshed_payload["results"])


@pytest.mark.django_db
def test_workspace_access_request_notifications_cover_review_and_approval():
    user_model = get_user_model()
    reviewer = user_model.objects.create_user(
        email="reviewer@example.com",
        password="devpass123",
        username="reviewer",
        first_name="Giulia",
        last_name="Bassi",
        language="it",
    )
    requester = user_model.objects.create_user(
        email="requester@example.com",
        password="devpass123",
        username="requester",
        first_name="Marco",
        last_name="Rossi",
        language="it",
    )
    workspace = Workspace.objects.create(name="Impresa Centrale")
    reviewer_profile = Profile.objects.create(
        workspace=workspace,
        user=reviewer,
        email=reviewer.email,
        role=WorkspaceRole.OWNER,
        first_name="Giulia",
        last_name="Bassi",
        language="it",
        position="Amministratrice",
    )

    result = create_workspace_access_request(
        requester,
        workspace_id=workspace.id,
        email=requester.email,
        first_name="Marco",
        last_name="Rossi",
        phone="+39 333 1234567",
        language="it",
        position="Capocantiere",
        message="Vorrei seguire il progetto di ristrutturazione del Lotto B.",
    )

    assert result["status"] == "request_sent"
    review_notification = Notification.objects.get(recipient_profile=reviewer_profile)
    assert review_notification.kind == "workspace.access_request.created"
    assert "Marco Rossi" in review_notification.subject
    assert review_notification.data["workspace_id"] == workspace.id

    access_request = WorkspaceAccessRequest.objects.get(id=result["request"]["id"])
    approval_result = approve_workspace_access_request(
        request_id=access_request.id,
        token=access_request.request_token,
        reviewed_by=reviewer,
    )

    assert approval_result["status"] == "approved"
    requester_profile = Profile.objects.get(workspace=workspace, user=requester)
    approval_notification = Notification.objects.filter(
        recipient_profile=requester_profile,
        kind="workspace.access_request.approved",
    ).get()
    assert approval_notification.subject == f"{workspace.name} ha approvato la tua richiesta"
    assert approval_notification.sender_profile_id == reviewer_profile.id
    assert approval_notification.data["status"] == "approved"


@pytest.mark.django_db
def test_project_notifications_cover_mentions_replies_documents_and_team_additions():
    workspace = Workspace.objects.create(name="Impresa Centrale", email="office@example.com")
    owner_user, owner_profile = create_workspace_user(
        workspace=workspace,
        email="owner.project@example.com",
        password="devpass123",
        first_name="Marco",
        last_name="Carminati",
        role=WorkspaceRole.OWNER,
    )
    teammate_user, teammate_profile = create_workspace_user(
        workspace=workspace,
        email="teammate.project@example.com",
        password="devpass123",
        first_name="Alessandro",
        last_name="Coti",
        role=WorkspaceRole.WORKER,
    )
    added_user, added_profile = create_workspace_user(
        workspace=workspace,
        email="added.project@example.com",
        password="devpass123",
        first_name="Sara",
        last_name="Mancini",
        role=WorkspaceRole.WORKER,
    )

    project = Project.objects.create(
        workspace=workspace,
        created_by=owner_profile,
        name="Residenza Test Notifiche",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=30),
    )
    ProjectMember.objects.create(
        project=project,
        profile=owner_profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    ProjectMember.objects.create(
        project=project,
        profile=teammate_profile,
        role=WorkspaceRole.WORKER,
        status=ProjectMemberStatus.ACTIVE,
    )

    task = ProjectTask.objects.create(
        project=project,
        name="Predisposizione corridoio nord",
        assigned_company=workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=7),
        progress=10,
    )
    activity = ProjectActivity.objects.create(
        task=task,
        title="Verifica tracciati",
        status="progress",
        datetime_start=timezone.now(),
        datetime_end=timezone.now() + timedelta(hours=6),
    )

    owner_token = login_and_get_token(email=owner_user.email, password="devpass123")
    teammate_token = login_and_get_token(email=teammate_user.email, password="devpass123")
    added_token = login_and_get_token(email=added_user.email, password="devpass123")
    client = Client()

    create_post_response = client.post(
        f"/api/v1/activities/{activity.id}/posts",
        data={
            "text": "Alessandro controlla la derivazione sul corridoio nord prima della chiusura.",
            "post_kind": "work-progress",
            "is_public": "false",
            "alert": "false",
            "source_language": "it",
            "mentioned_profile_ids": str(teammate_profile.id),
        },
        **auth_header(owner_token),
    )
    assert create_post_response.status_code == 201
    post_id = create_post_response.json()["id"]

    teammate_notifications = client.get("/api/v1/notifications?limit=20", **auth_header(teammate_token))
    assert teammate_notifications.status_code == 200
    mention_notification = teammate_notifications.json()["results"][0]
    assert mention_notification["kind"] == "project.mention.post"
    assert mention_notification["data"]["category"] == "mention"
    assert mention_notification["target"]["project_id"] == project.id
    assert mention_notification["target"]["post_id"] == post_id
    assert mention_notification["data"]["target_tab"] == "task"

    teammate_comment_response = client.post(
        f"/api/v1/posts/{post_id}/comments",
        data={
            "text": "Ricevuto, faccio il controllo entro pranzo.",
            "source_language": "it",
        },
        **auth_header(teammate_token),
    )
    assert teammate_comment_response.status_code == 201
    comment_id = teammate_comment_response.json()["id"]

    owner_reply_response = client.post(
        f"/api/v1/posts/{post_id}/comments",
        data={
            "text": "Perfetto, appena chiudi aggiorna anche la foto nel thread.",
            "source_language": "it",
            "parent": str(comment_id),
        },
        **auth_header(owner_token),
    )
    assert owner_reply_response.status_code == 201
    reply_id = owner_reply_response.json()["id"]

    teammate_notifications = client.get("/api/v1/notifications?limit=20", **auth_header(teammate_token))
    assert teammate_notifications.status_code == 200
    reply_notification = next(
        item for item in teammate_notifications.json()["results"] if item["kind"] == "project.comment.reply"
    )
    assert reply_notification["target"]["comment_id"] == reply_id
    assert reply_notification["data"]["category"] == "comment"

    upload_document_response = client.post(
        f"/api/v1/projects/{project.id}/documents",
        data={
            "title": "Verbale sopralluogo 05-04",
            "description": "Stato avanzamento e punti aperti del corridoio nord.",
            "document": SimpleUploadedFile("verbale.pdf", b"%PDF-1.4 notifiche", content_type="application/pdf"),
        },
        **auth_header(owner_token),
    )
    assert upload_document_response.status_code == 201
    document_id = upload_document_response.json()["id"]

    teammate_notifications = client.get("/api/v1/notifications?limit=20", **auth_header(teammate_token))
    assert teammate_notifications.status_code == 200
    document_notification = next(
        item for item in teammate_notifications.json()["results"] if item["kind"] == "project.document.created"
    )
    assert document_notification["target"]["document_id"] == document_id
    assert document_notification["data"]["target_doc"] == f"document:{document_id}"

    add_member_response = client.post(
        f"/api/v1/projects/{project.id}/team",
        data=json.dumps(
            {
                "profile": added_profile.id,
                "role": WorkspaceRole.WORKER,
                "is_external": False,
            }
        ),
        content_type="application/json",
        **auth_header(owner_token),
    )
    assert add_member_response.status_code == 201

    added_notifications = client.get("/api/v1/notifications?limit=20", **auth_header(added_token))
    assert added_notifications.status_code == 200
    team_notification = next(
        item for item in added_notifications.json()["results"] if item["kind"] == "project.member.added"
    )
    assert team_notification["data"]["category"] == "team"
    assert team_notification["target"]["project_id"] == project.id
    assert team_notification["data"]["target_tab"] == "team"
