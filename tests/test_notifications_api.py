import json
from base64 import b64decode
from datetime import date, timedelta
from pathlib import PurePosixPath

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from edilcloud.modules.notifications.models import (
    Notification,
    NotificationDevice,
    NotificationPushDelivery,
    NotificationPushDeliveryStatus,
)
from edilcloud.modules.notifications.catalog import (
    build_project_activity_notification,
    build_project_document_notification,
    build_project_task_notification,
    build_project_thread_notification,
)
from edilcloud.modules.notifications.push import (
    NotificationPushError,
    NotificationPushInvalidToken,
    build_push_data_payload,
    dispatch_notification_push,
)
from edilcloud.modules.notifications.services import create_notification
from edilcloud.modules.projects.models import (
    PostAttachment,
    PostKind,
    Project,
    ProjectInviteCode,
    ProjectActivity,
    ProjectDocument,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPost,
    ProjectTask,
)
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceAccessRequest, WorkspaceRole
from edilcloud.modules.workspaces.services import (
    approve_workspace_access_request,
    create_workspace_invite,
    create_workspace_access_request,
)
from edilcloud.modules.projects.services import generate_project_invite


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


def tiny_png_file(name: str = "image.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(
        name,
        b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9l9m0AAAAASUVORK5CYII="
        ),
        content_type="image/png",
    )


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
def test_workspace_invite_creates_notification_for_existing_user_with_media_payload():
    workspace = Workspace.objects.create(name="Workspace Inviti", logo="workspaces/logos/workspace-inviti.png")
    owner_user, owner_profile = create_workspace_user(
        workspace=workspace,
        email="owner.invites@example.com",
        password="devpass123",
        first_name="Luca",
        last_name="Ferretti",
        role=WorkspaceRole.OWNER,
    )
    recipient_workspace = Workspace.objects.create(name="Workspace Ricezione")
    recipient_user, recipient_profile = create_workspace_user(
        workspace=recipient_workspace,
        email="recipient.invites@example.com",
        password="devpass123",
        first_name="Anna",
        last_name="Bianchi",
        role=WorkspaceRole.WORKER,
    )

    invite_payload = create_workspace_invite(
        owner_user,
        workspace_id=workspace.id,
        email=recipient_user.email,
        role=WorkspaceRole.DELEGATE,
        position="Direzione lavori",
    )

    notification = Notification.objects.get(
        recipient_profile=recipient_profile,
        kind="workspace.invite.created",
    )
    assert invite_payload["company"]["id"] == workspace.id
    assert "Workspace Inviti" in notification.subject
    assert notification.data["workspace_id"] == workspace.id
    assert notification.data["role"] == WorkspaceRole.DELEGATE
    assert notification.data["image_url"].endswith("workspace-inviti.png")

    push_payload = build_push_data_payload(notification)
    assert push_payload["image_url"].endswith("workspace-inviti.png")


@pytest.mark.django_db
def test_project_invite_creates_notification_for_existing_user():
    workspace = Workspace.objects.create(name="Impresa Centrale")
    owner_user, owner_profile = create_workspace_user(
        workspace=workspace,
        email="owner.project.invites@example.com",
        password="devpass123",
        first_name="Marco",
        last_name="Conti",
        role=WorkspaceRole.OWNER,
    )
    recipient_workspace = Workspace.objects.create(name="Workspace Ricezione Progetto")
    recipient_user, recipient_profile = create_workspace_user(
        workspace=recipient_workspace,
        email="recipient.project.invites@example.com",
        password="devpass123",
        first_name="Giulia",
        last_name="Neri",
        role=WorkspaceRole.WORKER,
    )

    project = Project.objects.create(
        workspace=workspace,
        created_by=owner_profile,
        name="Residenza Le Querce",
        logo="projects/logos/residenza-le-querce.png",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=30),
    )
    ProjectMember.objects.create(
        project=project,
        profile=owner_profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )

    generate_project_invite(
        profile=owner_profile,
        project_id=project.id,
        email=recipient_user.email,
    )

    invite = ProjectInviteCode.objects.get(project=project, email=recipient_user.email)
    notification = Notification.objects.get(
        recipient_profile=recipient_profile,
        kind="project.invite.created",
    )
    assert notification.object_id == invite.id
    assert notification.data["project_name"] == project.name
    assert notification.data["invite_code"] == invite.unique_code
    assert notification.data["image_url"].endswith("residenza-le-querce.png")


@pytest.mark.django_db
def test_notification_catalog_builders_enrich_task_and_activity_payloads():
    workspace = Workspace.objects.create(
        name="Impresa Costruzioni",
        logo="workspaces/logos/impresa-costruzioni.png",
    )
    owner_user, owner_profile = create_workspace_user(
        workspace=workspace,
        email="owner.catalog@example.com",
        password="devpass123",
        first_name="Luca",
        last_name="Mauri",
        role=WorkspaceRole.OWNER,
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=owner_profile,
        name="Cantiere Atlas",
        logo="projects/logos/cantiere-atlas.png",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=20),
    )
    task = ProjectTask.objects.create(
        project=project,
        name="Fondazioni blocco A",
        assigned_company=workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=5),
        progress=45,
        alert=True,
    )
    activity = ProjectActivity.objects.create(
        task=task,
        title="Tracciamento e quote",
        status="progress",
        progress=60,
        alert=True,
        datetime_start=timezone.now(),
        datetime_end=timezone.now() + timedelta(hours=4),
    )

    task_blueprint = build_project_task_notification(
        task=task,
        actor_profile=owner_profile,
        action="updated",
        audience="generic",
    )
    assert task_blueprint.kind == "project.task.updated"
    assert task_blueprint.data["category"] == "task"
    assert task_blueprint.data["alert"] is True
    assert task_blueprint.data["image_url"].endswith("cantiere-atlas.png")

    activity_blueprint = build_project_activity_notification(
        activity=activity,
        actor_profile=owner_profile,
        action="updated",
        audience="generic",
    )
    assert activity_blueprint.kind == "project.activity.updated"
    assert activity_blueprint.data["category"] == "activity"
    assert activity_blueprint.data["progress"] == 60
    assert activity_blueprint.data["image_url"].endswith("cantiere-atlas.png")


@pytest.mark.django_db
def test_notification_catalog_thread_and_document_builders_include_visual_media():
    workspace = Workspace.objects.create(name="Impresa Media")
    user, profile = create_workspace_user(
        workspace=workspace,
        email="media.catalog@example.com",
        password="devpass123",
        first_name="Sara",
        last_name="Colombo",
        role=WorkspaceRole.OWNER,
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Media",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=15),
    )
    task = ProjectTask.objects.create(
        project=project,
        name="Tamponamenti",
        assigned_company=workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=3),
        progress=10,
    )
    post = ProjectPost.objects.create(
        project=project,
        task=task,
        author=profile,
        post_kind=PostKind.WORK_PROGRESS,
        text="Caricate le foto del fronte ovest.",
        original_text="Caricate le foto del fronte ovest.",
        source_language="it",
        display_language="it",
        alert=False,
        is_public=False,
    )
    PostAttachment.objects.create(post=post, file=tiny_png_file("fronte-ovest.png"))

    thread_blueprint = build_project_thread_notification(
        kind="project.post.created",
        subject="Nuovo aggiornamento",
        actor_profile=profile,
        post=post,
        category="post",
        action="created",
        snippet="Caricate le foto del fronte ovest.",
    )
    assert thread_blueprint.post_id == post.id
    thread_image_name = PurePosixPath(thread_blueprint.data["image_url"]).name
    assert thread_image_name.startswith("fronte-ovest")
    assert thread_image_name.endswith(".png")

    document = ProjectDocument.objects.create(
        project=project,
        title="Schema facciata",
        document=tiny_png_file("schema-facciata.png"),
    )
    document_blueprint = build_project_document_notification(
        kind="project.document.created",
        action="created",
        actor_profile=profile,
        project=project,
        document_id=document.id,
        document_title=document.title,
        file_field=document.document,
    )
    assert document_blueprint.document_id == document.id
    document_image_name = PurePosixPath(document_blueprint.data["image_url"]).name
    assert document_image_name.startswith("schema-facciata")
    assert document_image_name.endswith(".png")


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


@pytest.mark.django_db
def test_notification_devices_register_and_unregister_follow_active_profile():
    workspace = Workspace.objects.create(name="Workspace Push")
    user, profile = create_workspace_user(
        workspace=workspace,
        email="push-device@example.com",
        password="devpass123",
        first_name="Paolo",
        last_name="Test",
        role=WorkspaceRole.MANAGER,
    )
    token = login_and_get_token(email=user.email, password="devpass123")
    client = Client()

    register_response = client.post(
        "/api/v1/notifications/devices/register",
        data=json.dumps(
            {
                "token": "fcm-token-abcdefghijklmnopqrstuvwxyz-1234567890",
                "platform": "android",
                "installation_id": "install-1",
                "device_name": "Pixel 9",
                "locale": "it",
                "timezone": "Europe/Rome",
                "app_version": "1.0.0+1",
                "push_enabled": True,
            }
        ),
        content_type="application/json",
        **auth_header(token),
    )
    assert register_response.status_code == 200
    payload = register_response.json()
    assert payload["platform"] == "android"
    assert payload["installation_id"] == "install-1"
    assert payload["push_enabled"] is True
    assert payload["is_active"] is True

    device = NotificationDevice.objects.get(user=user, profile=profile)
    assert device.device_name == "Pixel 9"
    assert device.timezone == "Europe/Rome"

    unregister_response = client.post(
        "/api/v1/notifications/devices/unregister",
        data=json.dumps(
            {
                "token": "fcm-token-abcdefghijklmnopqrstuvwxyz-1234567890",
                "installation_id": "install-1",
            }
        ),
        content_type="application/json",
        **auth_header(token),
    )
    assert unregister_response.status_code == 200
    assert unregister_response.json()["updated"] == 1

    device.refresh_from_db()
    assert device.is_active is False


@pytest.mark.django_db
def test_active_workspace_profiles_include_unread_notification_count_per_profile():
    workspace_a = Workspace.objects.create(name="Workspace Alfa")
    workspace_b = Workspace.objects.create(name="Workspace Beta")
    user = get_user_model().objects.create_user(
        email="multi-workspace@example.com",
        password="devpass123",
        username="multi-workspace",
        first_name="Anna",
        last_name="Verdi",
        language="it",
    )
    profile_a = Profile.objects.create(
        workspace=workspace_a,
        user=user,
        email=user.email,
        role=WorkspaceRole.MANAGER,
        first_name="Anna",
        last_name="Verdi",
        language="it",
    )
    profile_b = Profile.objects.create(
        workspace=workspace_b,
        user=user,
        email=user.email,
        role=WorkspaceRole.WORKER,
        first_name="Anna",
        last_name="Verdi",
        language="it",
    )

    create_notification(
        recipient_profile=profile_a,
        subject="Nuova notifica A1",
        kind="workspace.notice",
    )
    create_notification(
        recipient_profile=profile_a,
        subject="Nuova notifica A2",
        kind="workspace.notice",
    )
    read_notification = create_notification(
        recipient_profile=profile_b,
        subject="Nuova notifica B1",
        kind="workspace.notice",
    )
    read_notification.read_at = timezone.now()
    read_notification.save(update_fields=["read_at", "updated_at"])

    token = login_and_get_token(email=user.email, password="devpass123")
    client = Client()

    response = client.get("/api/v1/workspaces/profiles/active", **auth_header(token))
    assert response.status_code == 200
    payload = response.json()

    by_profile_id = {item["id"]: item for item in payload}
    assert by_profile_id[profile_a.id]["unread_notification_count"] == 2
    assert by_profile_id[profile_b.id]["unread_notification_count"] == 0


@pytest.mark.django_db
def test_dispatch_notification_push_targets_all_active_devices_for_same_user_across_workspaces(monkeypatch):
    workspace_a = Workspace.objects.create(name="Workspace Push Alfa")
    workspace_b = Workspace.objects.create(name="Workspace Push Beta")
    other_workspace = Workspace.objects.create(name="Workspace Push Extra")

    user = get_user_model().objects.create_user(
        email="push-multi@example.com",
        password="devpass123",
        username="push-multi",
        first_name="Lara",
        last_name="Neri",
        language="it",
    )
    other_user = get_user_model().objects.create_user(
        email="push-other@example.com",
        password="devpass123",
        username="push-other",
        first_name="Piero",
        last_name="Blu",
        language="it",
    )

    profile_a = Profile.objects.create(
        workspace=workspace_a,
        user=user,
        email=user.email,
        role=WorkspaceRole.MANAGER,
        first_name="Lara",
        last_name="Neri",
        language="it",
    )
    profile_b = Profile.objects.create(
        workspace=workspace_b,
        user=user,
        email=user.email,
        role=WorkspaceRole.WORKER,
        first_name="Lara",
        last_name="Neri",
        language="it",
    )
    other_profile = Profile.objects.create(
        workspace=other_workspace,
        user=other_user,
        email=other_user.email,
        role=WorkspaceRole.WORKER,
        first_name="Piero",
        last_name="Blu",
        language="it",
    )

    device_a = NotificationDevice.objects.create(
        user=user,
        profile=profile_a,
        token="device-token-a-abcdefghijklmnopqrstuvwxyz-123456",
        platform="android",
        installation_id="inst-a",
        push_enabled=True,
        is_active=True,
    )
    device_b = NotificationDevice.objects.create(
        user=user,
        profile=profile_b,
        token="device-token-b-abcdefghijklmnopqrstuvwxyz-123456",
        platform="ios",
        installation_id="inst-b",
        push_enabled=True,
        is_active=True,
    )
    NotificationDevice.objects.create(
        user=other_user,
        profile=other_profile,
        token="device-token-c-abcdefghijklmnopqrstuvwxyz-123456",
        platform="android",
        installation_id="inst-c",
        push_enabled=True,
        is_active=True,
    )

    notification = create_notification(
        recipient_profile=profile_a,
        subject="Nuova segnalazione",
        kind="project.issue.created",
        project_id=99,
    )

    monkeypatch.setattr(
        "edilcloud.modules.notifications.push.push_enabled",
        lambda: True,
    )
    pushed_device_ids = []

    def fake_send_push(*, device, notification):
        assert notification.id is not None
        pushed_device_ids.append(device.id)
        return f"projects/demo/messages/{device.id}"

    monkeypatch.setattr(
        "edilcloud.modules.notifications.push._send_push",
        fake_send_push,
    )

    sent = dispatch_notification_push(notification)

    assert sent == 2
    assert set(pushed_device_ids) == {device_a.id, device_b.id}

    deliveries = list(
        NotificationPushDelivery.objects.filter(notification=notification).order_by("device_id")
    )
    assert [item.device_id for item in deliveries] == [device_a.id, device_b.id]
    assert all(item.status == NotificationPushDeliveryStatus.SENT for item in deliveries)
    assert all(item.attempt_count == 1 for item in deliveries)
    assert all(item.delivered_at is not None for item in deliveries)
    assert [item.provider_message_id for item in deliveries] == [
        f"projects/demo/messages/{device_a.id}",
        f"projects/demo/messages/{device_b.id}",
    ]


@pytest.mark.django_db
def test_dispatch_notification_push_marks_invalid_tokens_and_deactivates_device(monkeypatch):
    workspace = Workspace.objects.create(name="Workspace Invalid Token")
    user, profile = create_workspace_user(
        workspace=workspace,
        email="push-invalid@example.com",
        password="devpass123",
        first_name="Marta",
        last_name="Ferri",
        role=WorkspaceRole.MANAGER,
    )
    device = NotificationDevice.objects.create(
        user=user,
        profile=profile,
        token="device-token-invalid-abcdefghijklmnopqrstuvwxyz-123456",
        platform="android",
        installation_id="inst-invalid",
        push_enabled=True,
        is_active=True,
    )
    notification = create_notification(
        recipient_profile=profile,
        subject="Nuovo alert",
        kind="project.issue.created",
        project_id=17,
    )

    monkeypatch.setattr(
        "edilcloud.modules.notifications.push.push_enabled",
        lambda: True,
    )

    def fake_send_push(*, device, notification):
        raise NotificationPushInvalidToken("token revoked", code="UNREGISTERED")

    monkeypatch.setattr(
        "edilcloud.modules.notifications.push._send_push",
        fake_send_push,
    )

    sent = dispatch_notification_push(notification)

    assert sent == 0
    device.refresh_from_db()
    assert device.is_active is False
    assert device.last_push_error == "token revoked"

    delivery = NotificationPushDelivery.objects.get(notification=notification, device=device)
    assert delivery.status == NotificationPushDeliveryStatus.INVALID_TOKEN
    assert delivery.attempt_count == 1
    assert delivery.failed_at is not None
    assert delivery.error_code == "UNREGISTERED"
    assert delivery.error_message == "token revoked"
    assert delivery.delivered_at is None


@pytest.mark.django_db
def test_dispatch_notification_push_tracks_failed_attempts_without_deactivating_device(monkeypatch):
    workspace = Workspace.objects.create(name="Workspace Failed Push")
    user, profile = create_workspace_user(
        workspace=workspace,
        email="push-failed@example.com",
        password="devpass123",
        first_name="Paola",
        last_name="Villa",
        role=WorkspaceRole.MANAGER,
    )
    device = NotificationDevice.objects.create(
        user=user,
        profile=profile,
        token="device-token-failed-abcdefghijklmnopqrstuvwxyz-123456",
        platform="ios",
        installation_id="inst-failed",
        push_enabled=True,
        is_active=True,
    )
    notification = create_notification(
        recipient_profile=profile,
        subject="Nuovo documento",
        kind="project.document.created",
        project_id=23,
    )

    monkeypatch.setattr(
        "edilcloud.modules.notifications.push.push_enabled",
        lambda: True,
    )

    def fake_send_push(*, device, notification):
        raise NotificationPushError("gateway timeout", code="UNAVAILABLE")

    monkeypatch.setattr(
        "edilcloud.modules.notifications.push._send_push",
        fake_send_push,
    )

    sent = dispatch_notification_push(notification)

    assert sent == 0
    device.refresh_from_db()
    assert device.is_active is True
    assert device.last_push_error == "gateway timeout"

    delivery = NotificationPushDelivery.objects.get(notification=notification, device=device)
    assert delivery.status == NotificationPushDeliveryStatus.FAILED
    assert delivery.attempt_count == 1
    assert delivery.failed_at is not None
    assert delivery.error_code == "UNAVAILABLE"
    assert delivery.error_message == "gateway timeout"
