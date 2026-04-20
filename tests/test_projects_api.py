import json
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostKind,
    PostAttachment,
    PostComment,
    PostCommentTranslation,
    Project,
    ProjectActivity,
    ProjectCompanyColor,
    ProjectDocument,
    ProjectFolder,
    ProjectInviteCode,
    ProjectMember,
    ProjectMemberStatus,
    ProjectOperationalEvent,
    ProjectPhoto,
    ProjectPost,
    ProjectPostTranslation,
    ProjectScheduleLink,
    ProjectStatus,
    ProjectTask,
)
from edilcloud.modules.projects.gantt_import import ImportedActivity, ImportedPhase, ImportedPlan
from edilcloud.modules.projects import services as project_services
from edilcloud.modules.projects.services import (
    PROJECT_COMPANY_COLOR_PALETTE,
    build_project_company_color,
    project_company_color_distance,
)
from edilcloud.modules.workspaces.models import Workspace, WorkspaceRole
from edilcloud.platform.geocoding import GeocodingResult


def create_workspace_profile(*, email: str, password: str, workspace_name: str = "Cantieri Test"):
    user = get_user_model().objects.create_user(
        email=email,
        password=password,
        username=email.split("@")[0],
        first_name="Mario",
        last_name="Rossi",
        language="it",
    )
    workspace = Workspace.objects.create(name=workspace_name, email=email)
    profile = workspace.profiles.create(
        user=user,
        email=email,
        role=WorkspaceRole.OWNER,
        first_name="Mario",
        last_name="Rossi",
        language="it",
    )
    return user, workspace, profile


def auth_headers(client: Client, *, email: str, password: str) -> dict[str, str]:
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
    token = response.json()["token"]
    return {"HTTP_AUTHORIZATION": f"JWT {token}"}


def create_project_fixture(profile) -> tuple[Project, ProjectTask, ProjectActivity, ProjectPost]:
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Aurora",
        description="Rifacimento facciata",
        address="Via Roma 12",
        google_place_id="demo-place-id",
        latitude=45.4642,
        longitude=9.19,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=60),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )

    task = ProjectTask.objects.create(
        project=project,
        name="Ponteggi",
        assigned_company=profile.workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=14),
        progress=35,
        note="Montaggio lato strada",
        alert=True,
    )
    activity = ProjectActivity.objects.create(
        task=task,
        title="Montaggio campata A",
        description="Verifica ancoraggi",
        status="progress",
        datetime_start=timezone.now(),
        datetime_end=timezone.now() + timedelta(hours=8),
        note="Coordinare chiusura marciapiede",
        alert=True,
    )
    activity.workers.add(profile)

    alert_post = ProjectPost.objects.create(
        project=project,
        task=task,
        activity=activity,
        author=profile,
        post_kind=PostKind.ISSUE,
        text="Criticita su ancoraggio nord",
        original_text="Criticita su ancoraggio nord",
        source_language="it",
        display_language="it",
        alert=True,
        is_public=False,
    )
    ProjectPost.objects.create(
        project=project,
        task=task,
        activity=activity,
        author=profile,
        post_kind=PostKind.WORK_PROGRESS,
        text="Avanzamento regolare della squadra",
        original_text="Avanzamento regolare della squadra",
        source_language="it",
        display_language="it",
        alert=False,
        is_public=False,
    )

    folder = ProjectFolder.objects.create(
        project=project,
        name="Verbali",
        path="Verbali",
    )
    ProjectDocument.objects.create(
        project=project,
        folder=folder,
        title="Verbale 01",
        description="Verbale di avvio lavori",
        document=SimpleUploadedFile("verbale-01.pdf", b"%PDF-1.4 demo", content_type="application/pdf"),
    )
    ProjectPhoto.objects.create(
        project=project,
        title="Tavola generale",
        photo=SimpleUploadedFile("tavola.png", b"fake-image", content_type="image/png"),
    )

    return project, task, activity, alert_post


@pytest.mark.django_db
def test_projects_read_models_cover_list_overview_and_detail_routes():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.owner@example.com",
        password="devpass123",
    )
    project, task, _activity, alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="projects.owner@example.com", password="devpass123")

    list_response = client.get("/api/v1/projects", **headers)
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert len(list_payload) == 1
    assert list_payload[0]["id"] == project.id
    assert list_payload[0]["team_count"] == 1
    assert list_payload[0]["alert_count"] == 1

    detail_response = client.get(f"/api/v1/projects/{project.id}", **headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["name"] == "Cantiere Aurora"

    overview_response = client.get(f"/api/v1/projects/{project.id}/overview", **headers)
    assert overview_response.status_code == 200
    overview_payload = overview_response.json()
    assert len(overview_payload["tasks"]) == 1
    assert overview_payload["tasks"][0]["id"] == task.id
    assert overview_payload["tasks"][0]["activities"][0]["post_set"] == []
    assert len(overview_payload["team"]) == 1
    assert len(overview_payload["documents"]) == 1
    assert len(overview_payload["photos"]) == 1
    assert len(overview_payload["alertPosts"]) == 1
    assert overview_payload["alertPosts"][0]["id"] == alert_post.id
    assert len(overview_payload["recentPosts"]) == 2
    assert overview_payload["recentPosts"][0]["comment_set"] == []

    tasks_response = client.get(f"/api/v1/projects/{project.id}/tasks", **headers)
    assert tasks_response.status_code == 200
    assert tasks_response.json()[0]["activities"][0]["workers"][0]["id"] == profile.id

    team_response = client.get(f"/api/v1/projects/{project.id}/team", **headers)
    assert team_response.status_code == 200
    assert team_response.json()[0]["profile"]["id"] == profile.id

    alerts_response = client.get(f"/api/v1/projects/{project.id}/alerts", **headers)
    assert alerts_response.status_code == 200
    assert alerts_response.json()[0]["id"] == alert_post.id

    documents_response = client.get(f"/api/v1/projects/{project.id}/documents", **headers)
    assert documents_response.status_code == 200
    assert documents_response.json()[0]["title"] == "Verbale 01"

    photos_response = client.get(f"/api/v1/projects/{project.id}/photos", **headers)
    assert photos_response.status_code == 200
    assert photos_response.json()[0]["title"] == "Tavola generale"

    folders_response = client.get(f"/api/v1/projects/{project.id}/folders", **headers)
    assert folders_response.status_code == 200
    assert folders_response.json()[0]["path"] == "Verbali"

    gantt_response = client.get(f"/api/v1/projects/{project.id}/gantt", **headers)
    assert gantt_response.status_code == 200
    assert gantt_response.json()["tasks"][0]["id"] == task.id
    assert gantt_response.json()["links"] == []


@pytest.mark.django_db
def test_project_company_colors_are_persistent_per_project_and_drive_team_tasks_and_gantt():
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.colors@example.com",
        password="S3cretPass!",
    )
    workspace.color = "#111111"
    workspace.save(update_fields=["color"])
    headers = auth_headers(client, email="projects.colors@example.com", password="S3cretPass!")

    first_project, first_task, _first_activity, _first_post = create_project_fixture(profile)
    second_project, second_task, _second_activity, _second_post = create_project_fixture(profile)

    first_overview_response = client.get(f"/api/v1/projects/{first_project.id}/overview", **headers)
    assert first_overview_response.status_code == 200
    first_gantt_response = client.get(f"/api/v1/projects/{first_project.id}/gantt", **headers)
    assert first_gantt_response.status_code == 200
    second_gantt_response = client.get(f"/api/v1/projects/{second_project.id}/gantt", **headers)
    assert second_gantt_response.status_code == 200

    first_overview_payload = first_overview_response.json()
    first_task_color = first_overview_payload["tasks"][0]["assigned_company"]["color_project"]
    first_team_color = first_overview_payload["team"][0]["profile"]["company"]["color_project"]
    first_gantt_color = first_gantt_response.json()["tasks"][0]["assigned_company"]["color_project"]
    second_gantt_color = second_gantt_response.json()["tasks"][0]["assigned_company"]["color_project"]

    assert first_task_color
    assert first_task_color == first_team_color == first_gantt_color
    assert first_task_color != workspace.color
    assert second_gantt_color
    assert second_gantt_color != workspace.color
    assert second_gantt_color != first_task_color

    first_assignment = ProjectCompanyColor.objects.get(
        project=first_project,
        workspace=workspace,
    )
    second_assignment = ProjectCompanyColor.objects.get(
        project=second_project,
        workspace=workspace,
    )
    assert first_assignment.color_project == first_task_color
    assert second_assignment.color_project == second_gantt_color
    assert first_assignment.color_project != second_assignment.color_project


@pytest.mark.django_db
def test_project_team_patch_updates_company_color_and_keeps_it_persistent():
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.team-color@example.com",
        password="S3cretPass!",
    )
    headers = auth_headers(client, email="projects.team-color@example.com", password="S3cretPass!")

    project, _task, _activity, _post = create_project_fixture(profile)
    team_response = client.get(f"/api/v1/projects/{project.id}/team", **headers)
    assert team_response.status_code == 200
    owner_member_id = team_response.json()[0]["id"]

    patch_response = client.patch(
        f"/api/v1/projects/{project.id}/team/{owner_member_id}",
        data=json.dumps({"company_color_project": "#12AbCd"}),
        content_type="application/json",
        **headers,
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["profile"]["company"]["color_project"] == "#12abcd"

    refreshed_team_response = client.get(f"/api/v1/projects/{project.id}/team", **headers)
    assert refreshed_team_response.status_code == 200
    owner_entry = next(
        item for item in refreshed_team_response.json() if item["profile"]["id"] == profile.id
    )
    assert owner_entry["profile"]["company"]["color_project"] == "#12abcd"

    overview_response = client.get(f"/api/v1/projects/{project.id}/overview", **headers)
    assert overview_response.status_code == 200
    overview_payload = overview_response.json()
    assert overview_payload["team"][0]["profile"]["company"]["color_project"] == "#12abcd"
    assert overview_payload["tasks"][0]["assigned_company"]["color_project"] == "#12abcd"

    gantt_response = client.get(f"/api/v1/projects/{project.id}/gantt", **headers)
    assert gantt_response.status_code == 200
    assert gantt_response.json()["tasks"][0]["assigned_company"]["color_project"] == "#12abcd"

    assignment = ProjectCompanyColor.objects.get(project=project, workspace=workspace)
    assert assignment.color_project == "#12abcd"

    teammate_user = get_user_model().objects.create_user(
        email="projects.team-color.teammate@example.com",
        password="S3cretPass!",
        username="projects.team-color.teammate",
        first_name="Giulia",
        last_name="Verdi",
        language="it",
    )
    teammate_profile = workspace.profiles.create(
        user=teammate_user,
        email=teammate_user.email,
        role=WorkspaceRole.WORKER,
        first_name="Giulia",
        last_name="Verdi",
        language="it",
    )
    add_response = client.post(
        f"/api/v1/projects/{project.id}/team",
        data=json.dumps(
            {
                "profile": teammate_profile.id,
                "role": "w",
                "is_external": False,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert add_response.status_code == 201

    team_after_add_response = client.get(f"/api/v1/projects/{project.id}/team", **headers)
    assert team_after_add_response.status_code == 200
    teammate_entry = next(
        item for item in team_after_add_response.json() if item["profile"]["id"] == teammate_profile.id
    )
    owner_after_add_entry = next(
        item for item in team_after_add_response.json() if item["profile"]["id"] == profile.id
    )
    assert teammate_entry["profile"]["company"]["color_project"] == "#12abcd"
    assert owner_after_add_entry["profile"]["company"]["color_project"] == "#12abcd"


@pytest.mark.django_db
def test_project_team_compliance_route_and_role_updates_work_end_to_end():
    client = Client()
    owner_user, owner_workspace, owner_profile = create_workspace_profile(
        email="projects.compliance.owner@example.com",
        password="devpass123",
        workspace_name="Compliance Owner Workspace",
    )
    owner_workspace.workspace_type = "committente"
    owner_workspace.save(update_fields=["workspace_type"])

    project = Project.objects.create(
        workspace=owner_workspace,
        created_by=owner_profile,
        name="Cantiere Compliance",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=45),
    )
    ProjectMember.objects.create(
        project=project,
        profile=owner_profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
        project_role_codes=["committente"],
    )

    contractor_one_user = get_user_model().objects.create_user(
        email="projects.compliance.exec1@example.com",
        password="devpass123",
        username="projects-compliance-exec1",
        first_name="Luca",
        last_name="Neri",
        language="it",
    )
    contractor_one_workspace = Workspace.objects.create(
        name="Impresa Affidataria",
        email=contractor_one_user.email,
        workspace_type="impresa_affidataria",
    )
    contractor_one_profile = contractor_one_workspace.profiles.create(
        user=contractor_one_user,
        email=contractor_one_user.email,
        role=WorkspaceRole.OWNER,
        first_name="Luca",
        last_name="Neri",
        language="it",
    )
    ProjectMember.objects.create(
        project=project,
        profile=contractor_one_profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
        project_role_codes=["rspp", "addetto_primo_soccorso"],
    )

    contractor_two_user = get_user_model().objects.create_user(
        email="projects.compliance.exec2@example.com",
        password="devpass123",
        username="projects-compliance-exec2",
        first_name="Sara",
        last_name="Blu",
        language="it",
    )
    contractor_two_workspace = Workspace.objects.create(
        name="Impresa Esecutrice",
        email=contractor_two_user.email,
        workspace_type="impresa_esecutrice",
    )
    contractor_two_profile = contractor_two_workspace.profiles.create(
        user=contractor_two_user,
        email=contractor_two_user.email,
        role=WorkspaceRole.OWNER,
        first_name="Sara",
        last_name="Blu",
        language="it",
    )
    contractor_two_member = ProjectMember.objects.create(
        project=project,
        profile=contractor_two_profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
        project_role_codes=["csp", "cse"],
    )

    headers = auth_headers(client, email=owner_user.email, password="devpass123")

    initial_compliance_response = client.get(
        f"/api/v1/projects/{project.id}/team/compliance",
        **headers,
    )
    assert initial_compliance_response.status_code == 200
    initial_payload = initial_compliance_response.json()
    assert initial_payload["execution_company_count"] == 2
    assert initial_payload["requires_csp_cse"] is True
    assert initial_payload["compliant"] is False
    assert any(check["id"] == "addetti_emergenza" for check in initial_payload["missing_requirements"])

    update_response = client.patch(
        f"/api/v1/projects/{project.id}/team/{contractor_two_member.id}",
        data=json.dumps(
            {
                "project_role_codes": [
                    "csp",
                    "cse",
                    "addetto_antincendio_emergenza",
                ]
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["project_role_codes"] == [
        "csp",
        "cse",
        "addetto_antincendio_emergenza",
    ]

    contractor_two_member.refresh_from_db()
    assert contractor_two_member.project_role_codes == [
        "csp",
        "cse",
        "addetto_antincendio_emergenza",
    ]

    team_response = client.get(f"/api/v1/projects/{project.id}/team", **headers)
    assert team_response.status_code == 200
    serialized_contractor_two = next(
        item for item in team_response.json() if item["id"] == contractor_two_member.id
    )
    assert serialized_contractor_two["project_role_labels"] == [
        "CSP",
        "CSE",
        "Addetto antincendio / evacuazione / emergenza",
    ]

    final_compliance_response = client.get(
        f"/api/v1/projects/{project.id}/team/compliance",
        **headers,
    )
    assert final_compliance_response.status_code == 200
    final_payload = final_compliance_response.json()
    assert final_payload["compliant"] is True
    assert final_payload["missing_requirements"] == []
    assert set(final_payload["assigned_role_codes"]) == {
        "committente",
        "rspp",
        "addetto_primo_soccorso",
        "csp",
        "cse",
        "addetto_antincendio_emergenza",
    }


@pytest.mark.django_db
def test_adding_new_company_member_assigns_immediate_unique_project_color():
    client = Client()
    _user, owner_workspace, owner_profile = create_workspace_profile(
        email="projects.company-colors.owner@example.com",
        password="S3cretPass!",
    )
    headers = auth_headers(
        client,
        email="projects.company-colors.owner@example.com",
        password="S3cretPass!",
    )
    project, _task, _activity, _post = create_project_fixture(owner_profile)

    teammate_user = get_user_model().objects.create_user(
        email="projects.company-colors.alpha@example.com",
        password="S3cretPass!",
        username="projects.company-colors.alpha",
        first_name="Luca",
        last_name="Bianchi",
        language="it",
    )
    teammate_workspace = Workspace.objects.create(
        name="Impianti Alfa",
        email="alfa@example.com",
    )
    teammate_profile = teammate_workspace.profiles.create(
        user=teammate_user,
        email=teammate_user.email,
        role=WorkspaceRole.WORKER,
        first_name="Luca",
        last_name="Bianchi",
        language="it",
    )

    add_alpha_response = client.post(
        f"/api/v1/projects/{project.id}/team",
        data=json.dumps(
            {
                "profile": teammate_profile.id,
                "role": "w",
                "is_external": True,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert add_alpha_response.status_code == 201

    owner_assignment = ProjectCompanyColor.objects.get(project=project, workspace=owner_workspace)
    alpha_assignment = ProjectCompanyColor.objects.get(project=project, workspace=teammate_workspace)
    assert alpha_assignment.color_project
    assert alpha_assignment.color_project != owner_assignment.color_project

    second_user = get_user_model().objects.create_user(
        email="projects.company-colors.beta@example.com",
        password="S3cretPass!",
        username="projects.company-colors.beta",
        first_name="Anna",
        last_name="Neri",
        language="it",
    )
    second_workspace = Workspace.objects.create(
        name="Finiture Beta",
        email="beta@example.com",
    )
    second_profile = second_workspace.profiles.create(
        user=second_user,
        email=second_user.email,
        role=WorkspaceRole.WORKER,
        first_name="Anna",
        last_name="Neri",
        language="it",
    )

    add_beta_response = client.post(
        f"/api/v1/projects/{project.id}/team",
        data=json.dumps(
            {
                "profile": second_profile.id,
                "role": "w",
                "is_external": True,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert add_beta_response.status_code == 201

    beta_assignment = ProjectCompanyColor.objects.get(project=project, workspace=second_workspace)
    assert beta_assignment.color_project
    assert beta_assignment.color_project not in {
        owner_assignment.color_project,
        alpha_assignment.color_project,
    }


def test_google_material_project_company_palette_guarantees_at_least_fifty_unique_colors():
    colors = [build_project_company_color(project_id=7, attempt_index=index) for index in range(50)]
    assert len(colors) == 50
    assert len(set(colors)) == 50
    assert len(PROJECT_COMPANY_COLOR_PALETTE) >= 50


def test_google_material_project_company_palette_keeps_first_twenty_visually_separated():
    colors = [build_project_company_color(project_id=3, attempt_index=index) for index in range(20)]
    min_distance = min(
        project_company_color_distance(colors[left_index], colors[right_index])
        for left_index in range(len(colors))
        for right_index in range(left_index + 1, len(colors))
    )
    assert min_distance >= 18


@pytest.mark.django_db
def test_closed_project_summary_exposes_archive_retention_fields_and_marks_archive_when_due(settings):
    settings.PROJECT_ARCHIVE_AFTER_DAYS = 30
    settings.PROJECT_PURGE_AFTER_ARCHIVE_DAYS = 180

    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.archive.summary@example.com",
        password="devpass123",
        workspace_name="Archive Summary Workspace",
    )
    closed_at = timezone.now() - timedelta(days=45)
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Archiviato",
        date_start=date.today() - timedelta(days=120),
        date_end=date.today() - timedelta(days=30),
        status=ProjectStatus.CLOSED,
        closed_at=closed_at,
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="projects.archive.summary@example.com", password="devpass123")

    response = client.get(f"/api/v1/projects/{project.id}", **headers)
    assert response.status_code == 200
    payload = response.json()

    assert payload["closed_at"] is not None
    assert payload["archive_due_at"] is not None
    assert payload["archived_at"] is not None
    assert payload["purge_due_at"] is not None
    assert payload["last_export_at"] is None
    assert payload["owner_export_sent_at"] is None

    project.refresh_from_db()
    assert project.archive_due_at == closed_at + timedelta(days=30)
    assert project.purge_due_at == closed_at + timedelta(days=210)
    assert project.archived_at is not None


@pytest.mark.django_db
def test_project_archive_export_endpoint_returns_complete_zip_package():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.archive.export@example.com",
        password="devpass123",
        workspace_name="Archive Export Workspace",
    )
    project, task, activity, alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="projects.archive.export@example.com", password="devpass123")

    PostAttachment.objects.create(
        post=alert_post,
        file=SimpleUploadedFile("rilievo.txt", b"rilievo operativo", content_type="text/plain"),
    )
    comment = PostComment.objects.create(
        post=alert_post,
        author=profile,
        text="Commento di archivio",
        original_text="Commento di archivio",
        source_language="it",
        display_language="it",
    )
    CommentAttachment.objects.create(
        comment=comment,
        file=SimpleUploadedFile("nota.txt", b"nota allegata", content_type="text/plain"),
    )
    ProjectInviteCode.objects.create(
        project=project,
        created_by=profile,
        email="invite.archive@example.com",
    )
    ProjectScheduleLink.objects.create(
        project=project,
        source_task=task,
        target_task=task,
        link_type="e2s",
        lag_days=0,
        origin="test",
    )

    response = client.get(f"/api/v1/projects/{project.id}/archive/export", **headers)
    assert response.status_code == 200
    assert "attachment;" in response["Content-Disposition"]
    assert ".zip" in response["Content-Disposition"]

    archive_bytes = b"".join(response.streaming_content)
    archive = zipfile.ZipFile(BytesIO(archive_bytes))
    names = set(archive.namelist())

    assert "manifest/project.json" in names
    assert "manifest/retention-policy.json" in names
    assert "planning/gantt.json" in names
    assert "documents/documents.json" in names
    assert "threads/posts-full.json" in names
    assert any("verbale-01" in name and name.endswith(".pdf") for name in names)
    assert any("tavola" in name and name.endswith(".png") for name in names)
    assert any("rilievo" in name and name.endswith(".txt") for name in names)
    assert any("nota" in name and name.endswith(".txt") for name in names)

    manifest_payload = json.loads(archive.read("manifest/project.json").decode("utf-8"))
    assert manifest_payload["project"]["id"] == project.id
    assert manifest_payload["project"]["name"] == project.name

    retention_payload = json.loads(archive.read("manifest/retention-policy.json").decode("utf-8"))
    assert retention_payload["archive_after_days"] == 365
    assert retention_payload["purge_after_archive_days"] == 180

    project.refresh_from_db()
    assert project.last_export_at is not None


@pytest.mark.django_db
def test_project_gantt_import_preview_and_apply_create_tasks_activities_and_links():
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.import@example.com",
        password="devpass123",
        workspace_name="Import Workspace",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Import",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=90),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="projects.import@example.com", password="devpass123")

    csv_content = "\n".join(
        [
            "ID,Fase,Attivita,Inizio,Fine,Predecessori,Azienda",
            f"1,Scavi,,{date.today()},{date.today() + timedelta(days=4)},,{workspace.name}",
            f"2,Scavi,Scavo area,{date.today()},{date.today() + timedelta(days=1)},,{workspace.name}",
            f"3,Strutture,,{date.today() + timedelta(days=5)},{date.today() + timedelta(days=9)},1FS,{workspace.name}",
            f"4,Strutture,Getto base,{date.today() + timedelta(days=5)},{date.today() + timedelta(days=7)},2FS+1,{workspace.name}",
        ]
    )
    upload = SimpleUploadedFile("cronoprogramma.csv", csv_content.encode("utf-8"), content_type="text/csv")
    preview_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/import/preview",
        data={"file": upload},
        **headers,
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["summary"]["phases"] == 2
    assert preview_payload["summary"]["activities"] == 2
    assert preview_payload["summary"]["links"] == 2
    assert preview_payload["summary"]["unresolved_companies"] == 0

    apply_upload = SimpleUploadedFile("cronoprogramma.csv", csv_content.encode("utf-8"), content_type="text/csv")
    apply_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/import/apply",
        data={"file": apply_upload, "replace_existing": "true"},
        **headers,
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["applied"] is True
    assert ProjectTask.objects.filter(project=project).count() == 2
    assert ProjectActivity.objects.filter(task__project=project).count() == 2
    assert ProjectScheduleLink.objects.filter(project=project).count() == 2

    gantt_response = client.get(f"/api/v1/projects/{project.id}/gantt", **headers)
    assert gantt_response.status_code == 200
    gantt_payload = gantt_response.json()
    assert len(gantt_payload["tasks"]) == 2
    assert len(gantt_payload["links"]) == 2


@pytest.mark.django_db
def test_project_gantt_import_preview_supports_microsoft_project_xml():
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.import.xml@example.com",
        password="devpass123",
        workspace_name="Import XML Workspace",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Import XML",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=60),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="projects.import.xml@example.com", password="devpass123")

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<Project xmlns="http://schemas.microsoft.com/project">
  <MinutesPerDay>480</MinutesPerDay>
  <Tasks>
    <Task><UID>0</UID><ID>0</ID><Name>Project</Name><Summary>1</Summary></Task>
    <Task>
      <UID>1</UID><ID>1</ID><Name>Strutture</Name><OutlineLevel>1</OutlineLevel><Summary>1</Summary>
      <Start>{date.today()}T08:00:00</Start><Finish>{date.today() + timedelta(days=4)}T17:00:00</Finish>
      <Text1>{workspace.name}</Text1>
    </Task>
    <Task>
      <UID>2</UID><ID>2</ID><Name>Getto fondazioni</Name><OutlineLevel>2</OutlineLevel><Summary>0</Summary>
      <Start>{date.today()}T08:00:00</Start><Finish>{date.today() + timedelta(days=1)}T17:00:00</Finish>
      <PercentComplete>45</PercentComplete>
    </Task>
    <Task>
      <UID>3</UID><ID>3</ID><Name>Armature</Name><OutlineLevel>2</OutlineLevel><Summary>0</Summary>
      <Start>{date.today() + timedelta(days=2)}T08:00:00</Start><Finish>{date.today() + timedelta(days=4)}T17:00:00</Finish>
      <PredecessorLink><PredecessorUID>2</PredecessorUID><Type>1</Type><LinkLag>4800</LinkLag></PredecessorLink>
    </Task>
  </Tasks>
</Project>"""
    upload = SimpleUploadedFile("microsoft-project.xml", xml_content.encode("utf-8"), content_type="application/xml")
    preview_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/import/preview",
        data={"file": upload},
        **headers,
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["detected_format"] == "ms-project-xml"
    assert preview_payload["source_system"] == "microsoft-project"
    assert preview_payload["summary"]["phases"] == 1
    assert preview_payload["summary"]["activities"] == 2
    assert preview_payload["summary"]["links"] == 1


@pytest.mark.django_db
def test_project_gantt_import_preview_and_apply_support_microsoft_project_mpp():
    pytest.importorskip("jpype")
    pytest.importorskip("mpxj")
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.import.mpp@example.com",
        password="devpass123",
        workspace_name="Import MPP Workspace",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Import MPP",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=90),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="projects.import.mpp@example.com", password="devpass123")

    fixture_path = Path(__file__).parent / "data" / "sample-ms-project-task-links.mpp"
    mpp_bytes = fixture_path.read_bytes()

    preview_upload = SimpleUploadedFile(
        "task-links.mpp",
        mpp_bytes,
        content_type="application/vnd.ms-project",
    )
    preview_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/import/preview",
        data={"file": preview_upload},
        **headers,
    )
    if preview_response.status_code == 400:
        detail = preview_response.json().get("detail", "")
        if "FileSystemNotFoundException" in detail:
            pytest.skip("Il parser MPP locale su Windows non riesce a risolvere i jar di MPXJ.")
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["detected_format"] == "ms-project-mpp"
    assert preview_payload["source_system"] == "microsoft-project"
    assert preview_payload["summary"]["phases"] > 0
    assert preview_payload["summary"]["links"] > 0

    apply_upload = SimpleUploadedFile(
        "task-links.mpp",
        mpp_bytes,
        content_type="application/vnd.ms-project",
    )
    apply_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/import/apply",
        data={"file": apply_upload, "replace_existing": "true"},
        **headers,
    )
    assert apply_response.status_code == 200
    assert apply_response.json()["applied"] is True
    assert ProjectTask.objects.filter(project=project).count() == preview_payload["summary"]["phases"]
    assert ProjectScheduleLink.objects.filter(project=project).count() == preview_payload["summary"]["links"]


@pytest.mark.django_db
def test_project_gantt_import_apply_accepts_string_activity_dates(monkeypatch):
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.import.string-dates@example.com",
        password="devpass123",
        workspace_name="Import String Dates Workspace",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Import String Dates",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=30),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="projects.import.string-dates@example.com", password="devpass123")

    monkeypatch.setattr(
        "edilcloud.modules.projects.services.parse_gantt_import_file",
        lambda _uploaded_file: ImportedPlan(
            detected_format="ms-project-mpp",
            source_system="microsoft-project",
            phases=[
                ImportedPhase(
                    ref="phase:1",
                    name="Fase importata",
                    date_start="2026-04-10",
                    date_end="2026-04-15",
                    activities=[
                        ImportedActivity(
                            ref="activity:1",
                            title="Attivita importata",
                            date_start="2026-04-10",
                            date_end="2026-04-12",
                        ),
                    ],
                ),
            ],
            links=[],
            warnings=[],
            detected_company_labels=[],
        ),
    )

    apply_upload = SimpleUploadedFile(
        "task-links.mpp",
        b"fake-mpp-content",
        content_type="application/vnd.ms-project",
    )
    apply_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/import/apply",
        data={"file": apply_upload, "replace_existing": "true"},
        **headers,
    )

    assert apply_response.status_code == 200
    assert apply_response.json()["applied"] is True
    imported_task = ProjectTask.objects.get(project=project, name="Fase importata")
    imported_activity = ProjectActivity.objects.get(task=imported_task, title="Attivita importata")
    assert imported_task.date_start.isoformat() == "2026-04-10"
    assert imported_task.date_end.isoformat() == "2026-04-15"
    assert timezone.localtime(imported_activity.datetime_start).date().isoformat() == "2026-04-10"
    assert timezone.localtime(imported_activity.datetime_end).date().isoformat() == "2026-04-12"


@pytest.mark.django_db
def test_project_gantt_links_can_be_created_updated_deleted_and_cascade_task_delays():
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.links@example.com",
        password="devpass123",
        workspace_name="Links Workspace",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Vincoli",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=40),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    task_one = ProjectTask.objects.create(
        project=project,
        name="Scavi",
        assigned_company=workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=2),
        progress=10,
    )
    task_two = ProjectTask.objects.create(
        project=project,
        name="Fondazioni",
        assigned_company=workspace,
        date_start=date.today() + timedelta(days=3),
        date_end=date.today() + timedelta(days=5),
        progress=0,
    )
    headers = auth_headers(client, email="projects.links@example.com", password="devpass123")

    create_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/links",
        data=json.dumps(
            {
                "source": f"task-{task_one.id}",
                "target": f"task-{task_two.id}",
                "type": "e2s",
                "lag_days": 0,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert create_response.status_code == 201
    link_id = create_response.json()["id"]
    assert ProjectScheduleLink.objects.filter(project=project).count() == 1

    update_response = client.patch(
        f"/api/v1/projects/{project.id}/gantt/links/{link_id}",
        data=json.dumps({"lag_days": 2}),
        content_type="application/json",
        **headers,
    )
    assert update_response.status_code == 200
    task_two.refresh_from_db()
    assert task_two.date_start == date.today() + timedelta(days=5)
    assert task_two.date_end == date.today() + timedelta(days=7)

    delete_response = client.delete(
        f"/api/v1/projects/{project.id}/gantt/links/{link_id}",
        **headers,
    )
    assert delete_response.status_code == 200
    assert ProjectScheduleLink.objects.filter(project=project).count() == 0

    update_task_response = client.patch(
        f"/api/v1/tasks/{task_one.id}",
        data=json.dumps(
            {
                "name": task_one.name,
                "assigned_company": workspace.id,
                "date_start": str(task_one.date_start),
                "date_end": str(date.today() + timedelta(days=8)),
                "date_completed": None,
                "progress": task_one.progress,
                "note": "",
                "alert": False,
                "starred": False,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_task_response.status_code == 200
    task_two.refresh_from_db()
    assert task_two.date_start == date.today() + timedelta(days=5)
    assert task_two.date_end == date.today() + timedelta(days=7)


@pytest.mark.django_db
def test_activity_delay_expands_phase_and_pushes_linked_next_phase():
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.phase.guardrail@example.com",
        password="devpass123",
        workspace_name="Phase Guardrail Workspace",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Guard Rail",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=50),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    task_one = ProjectTask.objects.create(
        project=project,
        name="Fase A",
        assigned_company=workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=2),
    )
    task_two = ProjectTask.objects.create(
        project=project,
        name="Fase B",
        assigned_company=workspace,
        date_start=date.today() + timedelta(days=3),
        date_end=date.today() + timedelta(days=5),
    )
    activity_one = ProjectActivity.objects.create(
        task=task_one,
        title="Attivita A1",
        status="progress",
        progress=35,
        datetime_start=timezone.make_aware(datetime.combine(date.today(), datetime.min.time())),
        datetime_end=timezone.make_aware(datetime.combine(date.today() + timedelta(days=1), datetime.min.time())),
    )
    ProjectActivity.objects.create(
        task=task_two,
        title="Attivita B1",
        status="to-do",
        progress=0,
        datetime_start=timezone.make_aware(datetime.combine(date.today() + timedelta(days=3), datetime.min.time())),
        datetime_end=timezone.make_aware(datetime.combine(date.today() + timedelta(days=4), datetime.min.time())),
    )
    headers = auth_headers(client, email="projects.phase.guardrail@example.com", password="devpass123")

    link_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/links",
        data=json.dumps(
            {
                "source": f"task-{task_one.id}",
                "target": f"task-{task_two.id}",
                "type": "e2s",
                "lag_days": 0,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert link_response.status_code == 201

    update_activity_response = client.patch(
        f"/api/v1/activities/{activity_one.id}",
        data=json.dumps(
            {
                "title": activity_one.title,
                "description": "",
                "status": "progress",
                "progress": 60,
                "datetime_start": timezone.make_aware(datetime.combine(date.today(), datetime.min.time())).isoformat(),
                "datetime_end": timezone.make_aware(datetime.combine(date.today() + timedelta(days=5), datetime.min.time())).isoformat(),
                "workers": [],
                "note": "",
                "alert": False,
                "starred": False,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_activity_response.status_code == 200

    task_one.refresh_from_db()
    task_two.refresh_from_db()
    assert task_one.date_end == date.today() + timedelta(days=5)
    assert task_two.date_start == date.today() + timedelta(days=6)
    assert task_two.date_end == date.today() + timedelta(days=8)


@pytest.mark.django_db
def test_activity_level_gantt_links_push_successor_activity_and_expand_parent_phase():
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.activity.links@example.com",
        password="devpass123",
        workspace_name="Activity Links Workspace",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=profile,
        name="Cantiere Activity Links",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=30),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    task_one = ProjectTask.objects.create(
        project=project,
        name="Fase Uno",
        assigned_company=workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=1),
    )
    task_two = ProjectTask.objects.create(
        project=project,
        name="Fase Due",
        assigned_company=workspace,
        date_start=date.today() + timedelta(days=2),
        date_end=date.today() + timedelta(days=3),
    )
    activity_one = ProjectActivity.objects.create(
        task=task_one,
        title="Attivita 1",
        status="progress",
        progress=25,
        datetime_start=timezone.make_aware(datetime.combine(date.today(), datetime.min.time())),
        datetime_end=timezone.make_aware(datetime.combine(date.today(), datetime.min.time())),
    )
    activity_two = ProjectActivity.objects.create(
        task=task_two,
        title="Attivita 2",
        status="to-do",
        progress=0,
        datetime_start=timezone.make_aware(datetime.combine(date.today() + timedelta(days=2), datetime.min.time())),
        datetime_end=timezone.make_aware(datetime.combine(date.today() + timedelta(days=2), datetime.min.time())),
    )
    headers = auth_headers(client, email="projects.activity.links@example.com", password="devpass123")

    link_response = client.post(
        f"/api/v1/projects/{project.id}/gantt/links",
        data=json.dumps(
            {
                "source": f"activity-{activity_one.id}",
                "target": f"activity-{activity_two.id}",
                "type": "e2s",
                "lag_days": 0,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert link_response.status_code == 201

    update_activity_response = client.patch(
        f"/api/v1/activities/{activity_one.id}",
        data=json.dumps(
            {
                "title": activity_one.title,
                "description": "",
                "status": "progress",
                "progress": 55,
                "datetime_start": timezone.make_aware(datetime.combine(date.today(), datetime.min.time())).isoformat(),
                "datetime_end": timezone.make_aware(datetime.combine(date.today() + timedelta(days=4), datetime.min.time())).isoformat(),
                "workers": [],
                "note": "",
                "alert": False,
                "starred": False,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_activity_response.status_code == 200

    activity_two.refresh_from_db()
    task_two.refresh_from_db()
    assert timezone.localtime(activity_two.datetime_start).date() == date.today() + timedelta(days=5)
    assert timezone.localtime(activity_two.datetime_end).date() == date.today() + timedelta(days=5)
    assert task_two.date_end == date.today() + timedelta(days=5)


@pytest.mark.django_db
def test_project_task_activity_post_and_comment_mutations_work_end_to_end():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.mutations@example.com",
        password="devpass123",
        workspace_name="Mutation Workspace",
    )
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Mutazioni",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=30),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="projects.mutations@example.com", password="devpass123")

    create_task_response = client.post(
        f"/api/v1/projects/{project.id}/tasks",
        data=json.dumps(
            {
                "name": "Impianto elettrico",
                "assigned_company": profile.workspace_id,
                "date_start": str(date.today()),
                "date_end": str(date.today() + timedelta(days=7)),
                "progress": 10,
                "note": "Quadro generale",
                "alert": False,
                "starred": True,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert create_task_response.status_code == 201
    task_id = create_task_response.json()["id"]

    update_task_response = client.patch(
        f"/api/v1/tasks/{task_id}",
        data=json.dumps(
            {
                "name": "Impianto elettrico aggiornato",
                "assigned_company": profile.workspace_id,
                "date_start": str(date.today()),
                "date_end": str(date.today() + timedelta(days=10)),
                "date_completed": None,
                "progress": 20,
                "note": "Quadro generale e linee verticali",
                "alert": True,
                "starred": True,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_task_response.status_code == 200
    assert update_task_response.json()["alert"] is True

    create_activity_response = client.post(
        f"/api/v1/tasks/{task_id}/activities",
        data=json.dumps(
            {
                "title": "Tracciatura dorsali",
                "description": "Preparazione canaline",
                "status": "progress",
                "progress": 45,
                "datetime_start": timezone.now().isoformat(),
                "datetime_end": (timezone.now() + timedelta(hours=6)).isoformat(),
                "workers": [profile.id],
                "note": "Verificare percorso vano scala",
                "alert": False,
                "starred": True,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert create_activity_response.status_code == 201
    activity_id = create_activity_response.json()["id"]
    assert create_activity_response.json()["progress"] == 45
    assert create_activity_response.json()["status"] == "progress"

    update_activity_response = client.patch(
        f"/api/v1/activities/{activity_id}",
        data=json.dumps(
            {
                "title": "Tracciatura dorsali completata",
                "description": "Preparazione canaline e staffe",
                "status": "progress",
                "progress": 100,
                "datetime_start": timezone.now().isoformat(),
                "datetime_end": (timezone.now() + timedelta(hours=8)).isoformat(),
                "workers": [profile.id],
                "note": "Percorso vano scala verificato",
                "alert": True,
                "starred": False,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_activity_response.status_code == 200
    assert update_activity_response.json()["status"] == "completed"
    assert update_activity_response.json()["progress"] == 100
    assert ProjectActivity.objects.get(id=activity_id).progress == 100

    create_post_response = client.post(
        f"/api/v1/activities/{activity_id}/posts",
        data={
            "text": "Aggiornamento operativo dalla squadra elettrica",
            "post_kind": "work-progress",
            "is_public": "false",
            "alert": "true",
            "source_language": "it",
        },
        **headers,
    )
    assert create_post_response.status_code == 201
    post_id = create_post_response.json()["id"]

    posts_response = client.get(f"/api/v1/activities/{activity_id}/posts", **headers)
    assert posts_response.status_code == 200
    assert posts_response.json()[0]["id"] == post_id

    create_comment_response = client.post(
        f"/api/v1/posts/{post_id}/comments",
        data={
            "text": "Ricevuto, procediamo con verifica finale.",
            "source_language": "it",
        },
        **headers,
    )
    assert create_comment_response.status_code == 201
    comment_id = create_comment_response.json()["id"]
    assert create_comment_response.json()["parent"] is None

    create_reply_response = client.post(
        f"/api/v1/posts/{post_id}/comments",
        data={
            "text": "Verifica finale eseguita, tutto conforme.",
            "source_language": "it",
            "parent": str(comment_id),
        },
        **headers,
    )
    assert create_reply_response.status_code == 201
    reply_id = create_reply_response.json()["id"]
    assert create_reply_response.json()["parent"] == comment_id

    update_post_response = client.patch(
        f"/api/v1/posts/{post_id}",
        data=json.dumps(
            {
                "text": "Aggiornamento operativo validato",
                "post_kind": "documentation",
                "is_public": True,
                "alert": False,
                "source_language": "it",
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_post_response.status_code == 200
    assert update_post_response.json()["post_kind"] == "documentation"

    update_comment_response = client.patch(
        f"/api/v1/comments/{reply_id}",
        data=json.dumps(
            {
                "text": "Verifica finale completata e chiusa senza anomalie.",
                "source_language": "it",
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_comment_response.status_code == 200
    assert update_comment_response.json()["text"] == "Verifica finale completata e chiusa senza anomalie."
    assert update_comment_response.json()["parent"] == comment_id

    thread_response = client.get(f"/api/v1/activities/{activity_id}/posts", **headers)
    assert thread_response.status_code == 200
    thread_comments = thread_response.json()[0]["comment_set"]
    assert thread_comments[0]["id"] == comment_id
    assert thread_comments[0]["replies_set"][0]["id"] == reply_id

    delete_reply_response = client.delete(f"/api/v1/comments/{reply_id}", **headers)
    assert delete_reply_response.status_code == 204

    delete_comment_response = client.delete(f"/api/v1/comments/{comment_id}", **headers)
    assert delete_comment_response.status_code == 204

    delete_post_response = client.delete(f"/api/v1/posts/{post_id}", **headers)
    assert delete_post_response.status_code == 204


@pytest.mark.django_db
def test_project_post_and_comment_creates_are_idempotent_by_client_mutation_id():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.idempotent@example.com",
        password="devpass123",
        workspace_name="Idempotent Workspace",
    )
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Idempotenza",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=30),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="projects.idempotent@example.com", password="devpass123")

    task = ProjectTask.objects.create(
        project=project,
        name="Impianto meccanico",
        assigned_company=profile.workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=5),
    )
    activity = ProjectActivity.objects.create(
        task=task,
        title="Montaggio dorsali",
        status="progress",
        datetime_start=timezone.now(),
        datetime_end=timezone.now() + timedelta(hours=4),
    )

    create_post_headers = {
        **headers,
        "HTTP_X_EDILCLOUD_CLIENT_MUTATION_ID": "mobile-post-001",
    }
    first_post_response = client.post(
        f"/api/v1/activities/{activity.id}/posts",
        data={
            "text": "Aggiornamento offline con retry",
            "post_kind": "work-progress",
            "is_public": "true",
            "alert": "false",
            "source_language": "it",
        },
        **create_post_headers,
    )
    second_post_response = client.post(
        f"/api/v1/activities/{activity.id}/posts",
        data={
            "text": "Aggiornamento offline con retry",
            "post_kind": "work-progress",
            "is_public": "true",
            "alert": "false",
            "source_language": "it",
        },
        **create_post_headers,
    )

    assert first_post_response.status_code == 201
    assert second_post_response.status_code == 201
    assert first_post_response.json()["id"] == second_post_response.json()["id"]
    assert ProjectPost.objects.filter(activity=activity).count() == 1

    post_id = first_post_response.json()["id"]
    create_comment_headers = {
        **headers,
        "HTTP_X_EDILCLOUD_CLIENT_MUTATION_ID": "mobile-comment-001",
    }
    first_comment_response = client.post(
        f"/api/v1/posts/{post_id}/comments",
        data={
            "text": "Commento idempotente",
            "source_language": "it",
        },
        **create_comment_headers,
    )
    second_comment_response = client.post(
        f"/api/v1/posts/{post_id}/comments",
        data={
            "text": "Commento idempotente",
            "source_language": "it",
        },
        **create_comment_headers,
    )

    assert first_comment_response.status_code == 201
    assert second_comment_response.status_code == 201
    assert first_comment_response.json()["id"] == second_comment_response.json()["id"]
    assert PostComment.objects.filter(post_id=post_id).count() == 1


@pytest.mark.django_db
def test_project_feed_orders_by_latest_activity_and_resets_unread_when_post_changes_again():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.feed@example.com",
        password="devpass123",
        workspace_name="Feed Workspace",
    )
    project, _task, _activity, alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="projects.feed@example.com", password="devpass123")

    work_post = ProjectPost.objects.filter(project=project, post_kind=PostKind.WORK_PROGRESS).get()
    old_timestamp = timezone.now() - timedelta(days=2)
    newer_post_timestamp = timezone.now() - timedelta(days=1)
    ProjectPost.objects.filter(id=alert_post.id).update(
        published_date=old_timestamp,
        updated_at=old_timestamp,
    )
    ProjectPost.objects.filter(id=work_post.id).update(
        published_date=newer_post_timestamp,
        updated_at=newer_post_timestamp,
    )
    alert_post.refresh_from_db()
    work_post.refresh_from_db()

    first_comment = PostComment.objects.create(
        post=alert_post,
        author=profile,
        text="Serve un nuovo controllo lato nord.",
        original_text="Serve un nuovo controllo lato nord.",
        source_language="it",
        display_language="it",
    )

    feed_response = client.get("/api/v1/projects/feed?limit=10&offset=0", **headers)
    assert feed_response.status_code == 200
    feed_payload = feed_response.json()
    assert [item["id"] for item in feed_payload["items"][:2]] == [alert_post.id, work_post.id]
    assert feed_payload["items"][0]["feed_is_unread"] is True
    assert feed_payload["items"][0]["feed_seen_at"] is None
    assert abs(
        datetime.fromisoformat(feed_payload["items"][0]["last_activity_at"]) - first_comment.updated_at
    ) < timedelta(seconds=1)

    seen_response = client.post(f"/api/v1/posts/{alert_post.id}/seen", **headers)
    assert seen_response.status_code == 200
    assert seen_response.json()["post_id"] == alert_post.id
    assert seen_response.json()["is_unread"] is False

    refreshed_feed_response = client.get("/api/v1/projects/feed?limit=10&offset=0", **headers)
    assert refreshed_feed_response.status_code == 200
    refreshed_payload = refreshed_feed_response.json()
    assert refreshed_payload["items"][0]["id"] == alert_post.id
    assert refreshed_payload["items"][0]["feed_is_unread"] is False
    assert refreshed_payload["items"][0]["feed_seen_at"] is not None

    second_comment = PostComment.objects.create(
        post=alert_post,
        author=profile,
        text="Nuovo aggiornamento dopo la verifica.",
        original_text="Nuovo aggiornamento dopo la verifica.",
        source_language="it",
        display_language="it",
    )
    latest_activity = timezone.now() + timedelta(minutes=5)
    PostComment.objects.filter(id=second_comment.id).update(updated_at=latest_activity)

    unread_again_response = client.get("/api/v1/projects/feed?limit=10&offset=0", **headers)
    assert unread_again_response.status_code == 200
    unread_again_payload = unread_again_response.json()
    assert unread_again_payload["items"][0]["id"] == alert_post.id
    assert unread_again_payload["items"][0]["feed_is_unread"] is True
    assert abs(
        datetime.fromisoformat(unread_again_payload["items"][0]["last_activity_at"]) - latest_activity
    ) < timedelta(seconds=1)


@pytest.mark.django_db
def test_project_feed_bulk_seen_marks_requested_visible_threads():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.feed.bulk@example.com",
        password="devpass123",
        workspace_name="Feed Bulk Workspace",
    )
    project, _task, _activity, alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="projects.feed.bulk@example.com", password="devpass123")

    work_post = ProjectPost.objects.filter(project=project, post_kind=PostKind.WORK_PROGRESS).get()

    initial_feed_response = client.get("/api/v1/projects/feed?limit=10&offset=0", **headers)
    assert initial_feed_response.status_code == 200
    initial_items = initial_feed_response.json()["items"]
    assert {item["id"] for item in initial_items} == {alert_post.id, work_post.id}
    assert all(item["feed_is_unread"] is True for item in initial_items)

    bulk_seen_response = client.post(
        "/api/v1/projects/feed/seen",
        data=json.dumps({"post_ids": [alert_post.id, work_post.id, work_post.id, -2]}),
        content_type="application/json",
        **headers,
    )
    assert bulk_seen_response.status_code == 200
    bulk_seen_payload = bulk_seen_response.json()
    assert bulk_seen_payload["count"] == 2
    assert [item["post_id"] for item in bulk_seen_payload["items"]] == [alert_post.id, work_post.id]
    assert all(item["is_unread"] is False for item in bulk_seen_payload["items"])

    refreshed_feed_response = client.get("/api/v1/projects/feed?limit=10&offset=0", **headers)
    assert refreshed_feed_response.status_code == 200
    refreshed_by_id = {item["id"]: item for item in refreshed_feed_response.json()["items"]}
    assert refreshed_by_id[alert_post.id]["feed_is_unread"] is False
    assert refreshed_by_id[work_post.id]["feed_is_unread"] is False

    latest_comment = PostComment.objects.create(
        post=work_post,
        author=profile,
        text="Nuova nota operativa che deve far tornare il thread in cima.",
        original_text="Nuova nota operativa che deve far tornare il thread in cima.",
        source_language="it",
        display_language="it",
    )
    latest_activity = timezone.now() + timedelta(minutes=3)
    PostComment.objects.filter(id=latest_comment.id).update(updated_at=latest_activity)

    unread_again_response = client.get("/api/v1/projects/feed?limit=10&offset=0", **headers)
    assert unread_again_response.status_code == 200
    unread_again_payload = unread_again_response.json()
    assert unread_again_payload["items"][0]["id"] == work_post.id
    assert unread_again_payload["items"][0]["feed_is_unread"] is True
    assert unread_again_payload["items"][1]["feed_is_unread"] is False


@pytest.mark.django_db
def test_project_folder_and_document_routes_support_create_update_delete():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.documents@example.com",
        password="devpass123",
        workspace_name="Docs Workspace",
    )
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Documenti",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=15),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(client, email="projects.documents@example.com", password="devpass123")

    create_folder_response = client.post(
        f"/api/v1/projects/{project.id}/folders",
        data=json.dumps(
            {
                "name": "POS",
                "parent": None,
                "is_public": False,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert create_folder_response.status_code == 201
    folder_id = create_folder_response.json()["id"]

    upload_document_response = client.post(
        f"/api/v1/projects/{project.id}/documents",
        data={
            "title": "POS squadra A",
            "description": "Versione firmata",
            "folder": str(folder_id),
            "is_public": "false",
            "document": SimpleUploadedFile("pos-squadra-a.pdf", b"%PDF-1.4 pos", content_type="application/pdf"),
        },
        **headers,
    )
    assert upload_document_response.status_code == 201
    document_id = upload_document_response.json()["id"]

    update_folder_response = client.patch(
        f"/api/v1/folders/{folder_id}",
        data=json.dumps(
            {
                "name": "POS aggiornati",
                "parent": None,
                "is_public": True,
                "is_root": False,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_folder_response.status_code == 200
    assert update_folder_response.json()["name"] == "POS aggiornati"

    update_document_response = client.patch(
        f"/api/v1/documents/{document_id}",
        data=json.dumps(
            {
                "title": "POS squadra A rev.2",
                "description": "Versione firmata aggiornata",
                "folder": folder_id,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert update_document_response.status_code == 200
    assert update_document_response.json()["title"] == "POS squadra A rev.2"

    delete_document_response = client.delete(f"/api/v1/documents/{document_id}", **headers)
    assert delete_document_response.status_code == 204

    delete_folder_response = client.delete(f"/api/v1/folders/{folder_id}", **headers)
    assert delete_folder_response.status_code == 204


@pytest.mark.django_db
def test_project_document_upload_rejects_files_over_limit(settings):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.documents.limit@example.com",
        password="devpass123",
        workspace_name="Docs Limit Workspace",
    )
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Limiti",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=15),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    headers = auth_headers(
        client,
        email="projects.documents.limit@example.com",
        password="devpass123",
    )
    settings.PROJECT_DOCUMENT_MAX_UPLOAD_BYTES = 10

    response = client.post(
        f"/api/v1/projects/{project.id}/documents",
        data={
            "title": "Documento fuori limite",
            "description": "Troppo pesante",
            "is_public": "false",
            "document": SimpleUploadedFile(
                "fuori-limite.pdf",
                b"01234567890",
                content_type="application/pdf",
            ),
        },
        **headers,
    )

    assert response.status_code == 400
    assert "1 MB" in response.json()["detail"]
    assert "limite consentito" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_project_document_upload_supports_nested_additional_path_inside_existing_folder():
    from edilcloud.modules.projects.services import create_project_folder, upload_project_document

    _user, _workspace, profile = create_workspace_profile(
        email="projects.documents.nested@example.com",
        password="devpass123",
        workspace_name="Nested Docs Workspace",
    )
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Cartelle",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=15),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )

    base_folder = create_project_folder(
        profile=profile,
        project_id=project.id,
        name="Documenti tecnici",
        parent_id=None,
        is_public=False,
    )

    created_document = upload_project_document(
        profile=profile,
        project_id=project.id,
        uploaded_file=SimpleUploadedFile(
            "relazione-impianto.pdf",
            b"%PDF-1.4 nested",
            content_type="application/pdf",
        ),
        title="Relazione impianto",
        description="Upload annidato dentro cartella esistente",
        folder_id=base_folder["id"],
        additional_path="Impianti/Elettrico",
        is_public=False,
    )

    document = ProjectDocument.objects.select_related("folder").get(id=created_document["id"])
    assert document.folder is not None
    assert document.folder.path == "Documenti tecnici/Impianti/Elettrico"

    nested_paths = list(
        ProjectFolder.objects.filter(project=project).order_by("path").values_list("path", flat=True)
    )
    assert nested_paths == [
        "Documenti tecnici",
        "Documenti tecnici/Impianti",
        "Documenti tecnici/Impianti/Elettrico",
    ]


@pytest.mark.django_db
def test_project_inspection_report_endpoint_creates_document_and_phase_posts():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.inspection@example.com",
        password="devpass123",
        workspace_name="Inspection Workspace",
    )
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Verbali",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=20),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    task = ProjectTask.objects.create(
        project=project,
        name="Scavi e fondazioni",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=5),
        assigned_company_id=profile.workspace_id,
    )
    activity = ProjectActivity.objects.create(
        task=task,
        title="Tracciamento quote",
        datetime_start=timezone.now(),
        datetime_end=timezone.now() + timedelta(hours=2),
        status="progress",
    )
    headers = auth_headers(client, email="projects.inspection@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/projects/{project.id}/inspection-reports",
        data={
            "title": "Verbale sopralluogo fronte nord",
            "description": "Riepilogo tecnico del sopralluogo giornaliero",
            "general_summary": "Sopralluogo con verifica quote e scarichi.",
            "source_language": "it",
            "document": SimpleUploadedFile(
                "verbale-sopralluogo.pdf",
                b"%PDF-1.4 inspection",
                content_type="application/pdf",
            ),
            "entries": json.dumps(
                [
                    {
                        "task_id": task.id,
                        "summary": "Quote di scavo confermate. Da correggere il drenaggio lato est.",
                    },
                    {
                        "task_id": task.id,
                        "activity_id": activity.id,
                        "summary": "Tracciamento completato con richiesta di verifica finale prima del getto.",
                    },
                ]
            ),
        },
        **headers,
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["created_count"] == 2
    assert payload["document"]["title"] == "Verbale sopralluogo fronte nord"
    assert len(payload["posts"]) == 2

    document = ProjectDocument.objects.get(id=payload["document"]["id"])
    assert document.project_id == project.id
    assert document.document.name.endswith(".pdf")

    posts = list(
        ProjectPost.objects.filter(project=project).prefetch_related("attachments").order_by("id")
    )
    assert len(posts) == 2
    assert all(post.post_kind == PostKind.DOCUMENTATION for post in posts)
    assert posts[0].attachments.count() == 1
    assert posts[1].attachments.count() == 1
    assert "Verbale di sopralluogo" in posts[0].text
    assert "drive di progetto" in posts[0].text
    assert posts[0].task_id == task.id
    assert posts[0].activity_id is None
    assert posts[1].activity_id == activity.id


@pytest.mark.django_db
def test_project_mutations_publish_realtime_events(monkeypatch):
    from edilcloud.modules.projects.services import (
        create_activity_post,
        create_post_comment,
        create_project_folder,
        create_project_task,
        create_task_activity,
        delete_project_document,
        update_post,
        update_project_task,
        upload_project_document,
    )

    client = Client()
    published_events: list[dict] = []

    def capture_project_event(*, project_id: int, payload: dict):
        published_events.append({"project_id": project_id, "payload": payload})

    monkeypatch.setattr(
        "edilcloud.modules.projects.services.publish_project_event",
        capture_project_event,
    )

    _user, _workspace, profile = create_workspace_profile(
        email="projects.realtime@example.com",
        password="devpass123",
        workspace_name="Realtime Workspace",
    )
    headers = auth_headers(client, email="projects.realtime@example.com", password="devpass123")
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Cantiere Realtime",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=20),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )

    created_task = create_project_task(
        profile=profile,
        project_id=project.id,
        name="Opere murarie",
        assigned_company_id=profile.workspace_id,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=5),
        progress=15,
        note="Avvio pareti divisorie",
        alert=True,
        starred=False,
    )
    task = ProjectTask.objects.get(id=created_task["id"])

    update_project_task(
        profile=profile,
        task_id=task.id,
        name="Opere murarie aggiornate",
        assigned_company_id=profile.workspace_id,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=7),
        date_completed=None,
        progress=35,
        note="Pareti completate al 35%",
        alert=False,
        starred=True,
    )

    created_activity = create_task_activity(
        profile=profile,
        task_id=task.id,
        title="Tramezzi piano terra",
        description="Posa laterizi e controllo allineamenti",
        status="progress",
        progress=40,
        datetime_start=timezone.now(),
        datetime_end=timezone.now() + timedelta(hours=6),
        workers=[profile.id],
        note="Verifica vani porte",
        alert=True,
        starred=False,
    )
    activity = ProjectActivity.objects.get(id=created_activity["id"])
    assert activity.progress == 40

    created_post = create_activity_post(
        profile=profile,
        activity_id=activity.id,
        text="Rilevata una difformita su un allineamento.",
        post_kind=PostKind.ISSUE,
        is_public=False,
        alert=True,
        source_language="it",
        files=[],
        weather_payload={},
    )
    post = ProjectPost.objects.get(id=created_post["id"])

    created_comment = create_post_comment(
        profile=profile,
        post_id=post.id,
        text="Segnalazione presa in carico dal capocantiere.",
        parent_id=None,
        source_language="it",
        files=[],
    )
    comment = post.comments.get(id=created_comment["id"])

    update_post(
        profile=profile,
        post_id=post.id,
        text="Difformita risolta e validata.",
        post_kind=PostKind.ISSUE,
        is_public=False,
        alert=False,
        source_language="it",
        files=[],
        remove_media_ids=[],
    )

    created_folder = create_project_folder(
        profile=profile,
        project_id=project.id,
        name="Giornali lavori",
        parent_id=None,
        is_public=False,
    )
    folder = ProjectFolder.objects.get(id=created_folder["id"])

    created_document = upload_project_document(
        profile=profile,
        project_id=project.id,
        uploaded_file=SimpleUploadedFile(
            "giornale-lavori.pdf",
            b"%PDF-1.4 realtime",
            content_type="application/pdf",
        ),
        title="Giornale lavori 01",
        description="Prima registrazione operativa",
        folder_id=folder.id,
        is_public=False,
    )
    document = ProjectDocument.objects.get(id=created_document["id"])

    delete_project_document(profile=profile, document_id=document.id)

    event_types = [entry["payload"]["type"] for entry in published_events]
    assert event_types == [
        "task.created",
        "task.updated",
        "activity.created",
        "post.created",
        "comment.created",
        "post.resolved",
        "folder.created",
        "document.created",
        "document.deleted",
    ]
    assert all(entry["project_id"] == project.id for entry in published_events)
    assert published_events[0]["payload"]["taskId"] == task.id
    assert published_events[3]["payload"]["activityId"] == activity.id
    assert published_events[4]["payload"]["commentId"] == comment.id
    assert published_events[7]["payload"]["documentId"] == document.id
    assert published_events[8]["payload"]["data"]["is_deleted"] is True

    operational_events = list(
        ProjectOperationalEvent.objects.filter(project=project).order_by("occurred_at", "id")
    )
    assert len(operational_events) == len(event_types)

    timeline_by_type = {
        event.event_type: event.payload["timeline"]
        for event in operational_events
        if isinstance(event.payload, dict) and isinstance(event.payload.get("timeline"), dict)
    }
    assert timeline_by_type["task.created"]["event_kind"] == "task_created"
    assert any(
        detail["label"] == "Azienda"
        for detail in timeline_by_type["task.created"]["details"]
    )
    assert timeline_by_type["task.updated"]["event_kind"] == "task_updated"
    assert any(
        detail["label"] == "Progresso"
        for detail in timeline_by_type["task.updated"]["details"]
    )
    assert timeline_by_type["post.resolved"]["event_kind"] == "issue_resolved"
    assert timeline_by_type["document.deleted"]["event_kind"] == "document_deleted"
    assert timeline_by_type["document.deleted"]["is_deleted"] is True

    timeline_response = client.get(
        f"/api/v1/projects/{project.id}/timeline",
        data={"mode": "phase", "taskId": task.id},
        **headers,
    )
    assert timeline_response.status_code == 200

    timeline_payload = timeline_response.json()
    assert timeline_payload["mode"] == "phase"
    assert timeline_payload["task_id"] == task.id
    assert [event["event_kind"] for event in timeline_payload["events"]] == [
        "document_deleted",
        "document_created",
        "folder_created",
        "issue_resolved",
        "comment_added",
        "issue_opened",
        "activity_created",
        "task_updated",
        "task_created",
    ]
    assert timeline_payload["events"][0]["details"][0]["label"] == "Cartella"
    assert timeline_payload["events"][2]["scope"]["scope_kind"] == "project"
    assert timeline_payload["events"][5]["scope"]["scope_kind"] == "activity"
    assert timeline_payload["events"][5]["target_post_id"] == post.id


@pytest.mark.django_db
def test_workspace_team_and_company_lookup_routes_support_project_invites():
    client = Client()
    _user, workspace, profile = create_workspace_profile(
        email="projects.lookup@example.com",
        password="devpass123",
        workspace_name="Lookup Workspace",
    )
    delegate_user = get_user_model().objects.create_user(
        email="delegate.lookup@example.com",
        password="devpass123",
        username="delegate-lookup",
        first_name="Giulia",
        last_name="Bianchi",
        language="it",
    )
    workspace.profiles.create(
        user=delegate_user,
        email=delegate_user.email,
        role=WorkspaceRole.DELEGATE,
        first_name="Giulia",
        last_name="Bianchi",
        language="it",
    )
    headers = auth_headers(client, email="projects.lookup@example.com", password="devpass123")

    members_response = client.get("/api/v1/workspaces/current/members", **headers)
    assert members_response.status_code == 200
    members_payload = members_response.json()
    assert len(members_payload["approved"]) == 2
    assert members_payload["waiting"] == []

    companies_response = client.get("/api/v1/companies?query=Lookup", **headers)
    assert companies_response.status_code == 200
    assert companies_response.json()[0]["id"] == workspace.id

    contacts_response = client.get(f"/api/v1/companies/{workspace.id}/contacts", **headers)
    assert contacts_response.status_code == 200
    contacts_payload = contacts_response.json()
    assert contacts_payload["companyId"] == workspace.id
    assert len(contacts_payload["contacts"]) == 2
    assert contacts_payload["preferredContact"]["project_role"] in {"o", "d"}


@pytest.mark.django_db
def test_create_project_auto_geocodes_address_when_coordinates_missing(monkeypatch):
    client = Client()
    _user, _workspace, _profile = create_workspace_profile(
        email="projects.geocoding@example.com",
        password="devpass123",
        workspace_name="Geocoding Workspace",
    )
    headers = auth_headers(client, email="projects.geocoding@example.com", password="devpass123")

    monkeypatch.setattr(
        "edilcloud.modules.projects.services.geocode_address",
        lambda address: GeocodingResult(
            latitude=45.464203,
            longitude=9.189982,
            formatted_address="Via Torino 42, Milano, Italia",
        ),
    )

    create_response = client.post(
        "/api/v1/projects",
        data=json.dumps(
            {
                "name": "Cantiere Geocodifica",
                "description": "Indirizzo libero con geocoding automatico",
                "address": "Via Torino 42, Milano",
                "date_start": str(date.today()),
                "date_end": str(date.today() + timedelta(days=21)),
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["latitude"] == 45.464203
    assert payload["longitude"] == 9.189982
    assert payload["has_coordinates"] is True
    assert payload["location_source"] == "coordinates"
    assert "google.com/maps/search/" in (payload["map_url"] or "")


@pytest.mark.django_db
def test_create_project_rejects_invalid_coordinate_range():
    client = Client()
    _user, _workspace, _profile = create_workspace_profile(
        email="projects.coordinates@example.com",
        password="devpass123",
        workspace_name="Coordinate Workspace",
    )
    headers = auth_headers(client, email="projects.coordinates@example.com", password="devpass123")

    create_response = client.post(
        "/api/v1/projects",
        data=json.dumps(
            {
                "name": "Cantiere Coordinate Errate",
                "address": "Via Roma 1, Milano",
                "latitude": 123.456,
                "longitude": 9.19,
                "date_start": str(date.today()),
                "date_end": str(date.today() + timedelta(days=7)),
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert create_response.status_code == 400
    assert create_response.json()["detail"] == "Latitudine non valida."


@pytest.mark.django_db
def test_project_creator_keeps_workspace_role_when_not_owner():
    client = Client()
    user = get_user_model().objects.create_user(
        email="delegate.project@example.com",
        password="devpass123",
        username="delegate-project",
        first_name="Giulia",
        last_name="Bianchi",
        language="it",
    )
    workspace = Workspace.objects.create(name="Delegate Workspace", email=user.email)
    delegate_profile = workspace.profiles.create(
        user=user,
        email=user.email,
        role=WorkspaceRole.DELEGATE,
        first_name="Giulia",
        last_name="Bianchi",
        language="it",
    )
    headers = auth_headers(client, email=user.email, password="devpass123")

    create_response = client.post(
        "/api/v1/projects",
        data=json.dumps(
            {
                "name": "Cantiere Delegate",
                "description": "Nuovo cantiere da profilo delegate",
                "address": "Via Milano 24",
                "date_start": str(date.today()),
                "date_end": str(date.today() + timedelta(days=21)),
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert create_response.status_code == 201
    created_project = Project.objects.get(id=create_response.json()["id"])
    created_membership = ProjectMember.objects.get(project=created_project, profile=delegate_profile)
    assert created_membership.role == WorkspaceRole.DELEGATE


@pytest.mark.django_db
def test_internal_project_member_role_cannot_be_lower_than_workspace_role():
    client = Client()
    _user, workspace, owner_profile = create_workspace_profile(
        email="projects.rolefloor@example.com",
        password="devpass123",
        workspace_name="Role Floor Workspace",
    )
    project, _task, _activity, _post = create_project_fixture(owner_profile)

    teammate_user = get_user_model().objects.create_user(
        email="delegate.internal@example.com",
        password="devpass123",
        username="delegate-internal",
        first_name="Sara",
        last_name="Verdi",
        language="it",
    )
    teammate_profile = workspace.profiles.create(
        user=teammate_user,
        email=teammate_user.email,
        role=WorkspaceRole.DELEGATE,
        first_name="Sara",
        last_name="Verdi",
        language="it",
    )
    headers = auth_headers(client, email="projects.rolefloor@example.com", password="devpass123")

    add_member_response = client.post(
        f"/api/v1/projects/{project.id}/team",
        data=json.dumps(
            {
                "profile": teammate_profile.id,
                "role": WorkspaceRole.WORKER,
                "is_external": False,
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert add_member_response.status_code == 201
    assert add_member_response.json()["role"] == WorkspaceRole.DELEGATE
    teammate_membership = ProjectMember.objects.get(project=project, profile=teammate_profile)
    assert teammate_membership.role == WorkspaceRole.DELEGATE
    assert teammate_membership.is_external is False


@pytest.mark.django_db
def test_workspace_owner_with_legacy_project_role_mismatch_keeps_owner_permissions():
    client = Client()
    owner_user = get_user_model().objects.create_user(
        email="owner.mismatch@example.com",
        password="devpass123",
        username="owner-mismatch",
        first_name="Alessandro",
        last_name="Coti",
        language="it",
    )
    teammate_user = get_user_model().objects.create_user(
        email="worker.mismatch@example.com",
        password="devpass123",
        username="worker-mismatch",
        first_name="Marco",
        last_name="Carminati",
        language="it",
    )
    workspace = Workspace.objects.create(name="Mismatch Workspace", email=owner_user.email)
    owner_profile = workspace.profiles.create(
        user=owner_user,
        email=owner_user.email,
        role=WorkspaceRole.OWNER,
        first_name="Alessandro",
        last_name="Coti",
        language="it",
    )
    teammate_profile = workspace.profiles.create(
        user=teammate_user,
        email=teammate_user.email,
        role=WorkspaceRole.WORKER,
        first_name="Marco",
        last_name="Carminati",
        language="it",
    )
    project = Project.objects.create(
        workspace=workspace,
        created_by=owner_profile,
        name="Cantiere Mismatch",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=10),
    )
    ProjectMember.objects.create(
        project=project,
        profile=owner_profile,
        role=WorkspaceRole.MANAGER,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
    )
    headers = auth_headers(client, email=owner_user.email, password="devpass123")

    add_member_response = client.post(
        f"/api/v1/projects/{project.id}/team",
        data=json.dumps(
            {
                "profile": teammate_profile.id,
                "role": WorkspaceRole.WORKER,
                "is_external": False,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert add_member_response.status_code == 201

    team_response = client.get(f"/api/v1/projects/{project.id}/team", **headers)
    assert team_response.status_code == 200
    owner_entry = next(
        item for item in team_response.json() if item["profile"]["id"] == owner_profile.id
    )
    assert owner_entry["role"] == WorkspaceRole.OWNER

    stored_owner_membership = ProjectMember.objects.get(project=project, profile=owner_profile)
    assert stored_owner_membership.role == WorkspaceRole.OWNER


@pytest.mark.django_db
def test_project_permission_audit_worker_can_read_but_cannot_manage_members_or_tasks():
    client = Client()
    owner_user, workspace, owner_profile = create_workspace_profile(
        email="projects.permissions.owner@example.com",
        password="devpass123",
        workspace_name="Projects Permission Workspace",
    )
    project, _task, _activity, _post = create_project_fixture(owner_profile)

    worker_user = get_user_model().objects.create_user(
        email="projects.permissions.worker@example.com",
        password="devpass123",
        username="projects-permission-worker",
        first_name="Walter",
        last_name="Serra",
        language="it",
    )
    worker_profile = workspace.profiles.create(
        user=worker_user,
        email=worker_user.email,
        role=WorkspaceRole.WORKER,
        first_name="Walter",
        last_name="Serra",
        language="it",
    )
    candidate_user = get_user_model().objects.create_user(
        email="projects.permissions.candidate@example.com",
        password="devpass123",
        username="projects-permission-candidate",
        first_name="Caterina",
        last_name="Ferri",
        language="it",
    )
    candidate_profile = workspace.profiles.create(
        user=candidate_user,
        email=candidate_user.email,
        role=WorkspaceRole.WORKER,
        first_name="Caterina",
        last_name="Ferri",
        language="it",
    )
    outsider_email = "projects.permissions.outsider@example.com"
    _outsider_user, _outsider_workspace, _outsider_profile = create_workspace_profile(
        email=outsider_email,
        password="devpass123",
        workspace_name="Projects Outsider Workspace",
    )

    ProjectMember.objects.create(
        project=project,
        profile=worker_profile,
        role=WorkspaceRole.WORKER,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
    )

    worker_headers = auth_headers(
        client,
        email="projects.permissions.worker@example.com",
        password="devpass123",
    )

    assert client.get(f"/api/v1/projects/{project.id}/overview", **worker_headers).status_code == 200
    assert client.get(f"/api/v1/projects/{project.id}/team", **worker_headers).status_code == 200
    assert client.get(f"/api/v1/projects/{project.id}/gantt", **worker_headers).status_code == 200

    add_member_response = client.post(
        f"/api/v1/projects/{project.id}/team",
        data=json.dumps(
            {
                "profile": candidate_profile.id,
                "role": WorkspaceRole.WORKER,
                "is_external": False,
            }
        ),
        content_type="application/json",
        **worker_headers,
    )
    assert add_member_response.status_code == 400
    assert "Non hai permessi per invitare membri su questo progetto." in add_member_response.json()["detail"]

    invite_code_response = client.post(
        f"/api/v1/projects/{project.id}/invite-code",
        data=json.dumps({"email": "external.collab@example.com"}),
        content_type="application/json",
        **worker_headers,
    )
    assert invite_code_response.status_code == 400
    assert (
        "Non hai permessi per invitare aziende o collaboratori esterni."
        in invite_code_response.json()["detail"]
    )

    create_task_response = client.post(
        f"/api/v1/projects/{project.id}/tasks",
        data=json.dumps(
            {
                "name": "Task vietato al worker",
                "assigned_company": workspace.id,
                "date_start": str(date.today()),
                "date_end": str(date.today() + timedelta(days=5)),
                "progress": 0,
                "note": "Tentativo non autorizzato",
                "alert": False,
                "starred": False,
            }
        ),
        content_type="application/json",
        **worker_headers,
    )
    assert create_task_response.status_code == 400
    assert "Non hai permessi per creare task in questo progetto." in create_task_response.json()["detail"]

    outsider_headers = auth_headers(client, email=outsider_email, password="devpass123")
    overview_outsider_response = client.get(f"/api/v1/projects/{project.id}/overview", **outsider_headers)
    team_outsider_response = client.get(f"/api/v1/projects/{project.id}/team", **outsider_headers)
    gantt_outsider_response = client.get(f"/api/v1/projects/{project.id}/gantt", **outsider_headers)

    assert overview_outsider_response.status_code == 404
    assert team_outsider_response.status_code == 404
    assert gantt_outsider_response.status_code == 404


@pytest.mark.django_db
def test_project_file_download_endpoints_stream_project_assets_and_enforce_access_control():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.files@example.com",
        password="devpass123",
        workspace_name="Files Workspace",
    )
    project, _task, _activity, post = create_project_fixture(profile)
    comment = PostComment.objects.create(
        post=post,
        author=profile,
        text="Commento con allegato",
        original_text="Commento con allegato",
        source_language="it",
        display_language="it",
    )
    post_attachment = PostAttachment.objects.create(
        post=post,
        file=SimpleUploadedFile(
            "verbale-post.pdf",
            b"%PDF-1.4 post attachment",
            content_type="application/pdf",
        ),
    )
    comment_attachment = CommentAttachment.objects.create(
        comment=comment,
        file=SimpleUploadedFile(
            "nota-commento.txt",
            b"nota commento",
            content_type="text/plain",
        ),
    )
    document = ProjectDocument.objects.get(project=project)
    photo = ProjectPhoto.objects.get(project=project)

    headers = auth_headers(client, email="projects.files@example.com", password="devpass123")

    document_response = client.get(f"/api/v1/documents/{document.id}/file", **headers)
    assert document_response.status_code == 200
    assert document_response["Content-Type"] == "application/pdf"
    assert b"".join(document_response.streaming_content).startswith(b"%PDF-1.4")

    photo_response = client.get(f"/api/v1/photos/{photo.id}/file", **headers)
    assert photo_response.status_code == 200
    assert photo_response["Content-Type"] == "image/png"
    assert b"".join(photo_response.streaming_content) == b"fake-image"

    post_attachment_response = client.get(
        f"/api/v1/posts/attachments/{post_attachment.id}/file",
        **headers,
    )
    assert post_attachment_response.status_code == 200
    assert post_attachment_response["Content-Type"] == "application/pdf"
    assert b"".join(post_attachment_response.streaming_content).startswith(b"%PDF-1.4")

    comment_attachment_response = client.get(
        f"/api/v1/comments/attachments/{comment_attachment.id}/file",
        **headers,
    )
    assert comment_attachment_response.status_code == 200
    assert comment_attachment_response["Content-Type"] == "text/plain"
    assert b"".join(comment_attachment_response.streaming_content) == b"nota commento"

    outsider_email = "projects.files.outsider@example.com"
    _outsider_user, _outsider_workspace, _outsider_profile = create_workspace_profile(
        email=outsider_email,
        password="devpass123",
        workspace_name="Outsider Workspace",
    )
    outsider_headers = auth_headers(client, email=outsider_email, password="devpass123")

    assert client.get(f"/api/v1/documents/{document.id}/file", **outsider_headers).status_code == 404
    assert client.get(f"/api/v1/photos/{photo.id}/file", **outsider_headers).status_code == 404
    assert (
        client.get(
            f"/api/v1/posts/attachments/{post_attachment.id}/file",
            **outsider_headers,
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/comments/attachments/{comment_attachment.id}/file",
            **outsider_headers,
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_activity_posts_are_translated_and_cached_by_requested_locale(monkeypatch):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.translation.activity@example.com",
        password="devpass123",
    )
    _project, _task, activity, alert_post = create_project_fixture(profile)
    PostComment.objects.create(
        post=alert_post,
        author=profile,
        text="Serve rinforzo provvisorio lato nord.",
        original_text="Serve rinforzo provvisorio lato nord.",
        source_language="it",
        display_language="it",
    )
    headers = auth_headers(client, email="projects.translation.activity@example.com", password="devpass123")
    calls: list[tuple[str, str]] = []

    def fake_translate(*, source_text: str, source_language: str, target_language: str) -> str:
        calls.append((source_text, target_language))
        return f"[{target_language}] {source_text}"

    monkeypatch.setattr(project_services, "generate_project_content_translation", fake_translate)

    response = client.get(
        f"/api/v1/activities/{activity.id}/posts",
        HTTP_X_EDILCLOUD_LOCALE="ru",
        **headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 2
    translated_alert = next(item for item in payload if item["id"] == alert_post.id)
    assert translated_alert["display_language"] == "ru"
    assert translated_alert["is_translated"] is True
    assert translated_alert["text"].startswith("[ru] ")
    assert translated_alert["comment_set"][0]["display_language"] == "ru"
    assert translated_alert["comment_set"][0]["is_translated"] is True
    assert len(calls) == 3
    assert ProjectPostTranslation.objects.filter(target_language="ru").count() == 2
    assert PostCommentTranslation.objects.filter(target_language="ru").count() == 1

    def should_not_run(**_kwargs):
        raise AssertionError("La traduzione doveva arrivare dalla memoria, non dall'LLM.")

    monkeypatch.setattr(project_services, "generate_project_content_translation", should_not_run)
    cached_response = client.get(
        f"/api/v1/activities/{activity.id}/posts",
        HTTP_X_EDILCLOUD_LOCALE="ru",
        **headers,
    )
    assert cached_response.status_code == 200
    cached_payload = cached_response.json()
    cached_alert = next(item for item in cached_payload if item["id"] == alert_post.id)
    assert cached_alert["text"] == translated_alert["text"]
    assert cached_alert["comment_set"][0]["text"] == translated_alert["comment_set"][0]["text"]


@pytest.mark.django_db
def test_project_feed_translates_posts_once_and_reuses_saved_memory(monkeypatch):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.translation.feed@example.com",
        password="devpass123",
    )
    project, task, activity, alert_post = create_project_fixture(profile)
    ProjectPost.objects.create(
        project=project,
        task=task,
        author=profile,
        post_kind=PostKind.DOCUMENTATION,
        text="Verbale pronto per la condivisione.",
        original_text="Verbale pronto per la condivisione.",
        source_language="it",
        display_language="it",
        alert=False,
        is_public=False,
    )
    headers = auth_headers(client, email="projects.translation.feed@example.com", password="devpass123")
    translated_ids: list[str] = []

    def fake_translate(*, source_text: str, source_language: str, target_language: str) -> str:
        translated_ids.append(f"{target_language}:{source_text}")
        return f"[{target_language}] {source_text}"

    monkeypatch.setattr(project_services, "generate_project_content_translation", fake_translate)

    feed_response = client.get(
        "/api/v1/projects/feed?limit=10&offset=0",
        HTTP_X_EDILCLOUD_LOCALE="en",
        **headers,
    )

    assert feed_response.status_code == 200
    feed_payload = feed_response.json()
    assert len(feed_payload["items"]) >= 3
    assert all(item["display_language"] == "en" for item in feed_payload["items"][:3])
    assert all(item["is_translated"] is True for item in feed_payload["items"][:3])
    assert len(translated_ids) >= 3

    monkeypatch.setattr(
        project_services,
        "generate_project_content_translation",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("Il feed doveva riusare la memoria salvata.")),
    )
    second_feed_response = client.get(
        "/api/v1/projects/feed?limit=10&offset=0",
        HTTP_X_EDILCLOUD_LOCALE="en",
        **headers,
    )
    assert second_feed_response.status_code == 200
    second_payload = second_feed_response.json()
    assert second_payload["items"][0]["text"] == feed_payload["items"][0]["text"]


@pytest.mark.django_db
def test_updating_post_and_comment_invalidates_translation_memory(monkeypatch):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="projects.translation.update@example.com",
        password="devpass123",
    )
    _project, _task, activity, alert_post = create_project_fixture(profile)
    comment = PostComment.objects.create(
        post=alert_post,
        author=profile,
        text="Prima versione commento",
        original_text="Prima versione commento",
        source_language="it",
        display_language="it",
    )
    headers = auth_headers(client, email="projects.translation.update@example.com", password="devpass123")

    monkeypatch.setattr(
        project_services,
        "generate_project_content_translation",
        lambda *, source_text, source_language, target_language: f"[{target_language}] {source_text}",
    )
    warmup_response = client.get(
        f"/api/v1/activities/{activity.id}/posts",
        HTTP_X_EDILCLOUD_LOCALE="ru",
        **headers,
    )
    assert warmup_response.status_code == 200
    original_post_translation = ProjectPostTranslation.objects.get(post=alert_post, target_language="ru")
    original_comment_translation = PostCommentTranslation.objects.get(comment=comment, target_language="ru")

    post_update_calls: list[str] = []

    def fake_translate_after_update(*, source_text: str, source_language: str, target_language: str) -> str:
        post_update_calls.append(source_text)
        return f"[{target_language}] aggiornato: {source_text}"

    monkeypatch.setattr(project_services, "generate_project_content_translation", fake_translate_after_update)

    update_post_response = client.patch(
        f"/api/v1/posts/{alert_post.id}",
        data=json.dumps(
            {
                "text": "Testo aggiornato lato nord",
                "post_kind": PostKind.ISSUE,
                "is_public": False,
                "alert": True,
                "source_language": "it",
                "remove_media_ids": [],
                "mentioned_profile_ids": [],
            }
        ),
        content_type="application/json",
        HTTP_X_EDILCLOUD_LOCALE="ru",
        **headers,
    )
    assert update_post_response.status_code == 200
    updated_post_translation = ProjectPostTranslation.objects.get(post=alert_post, target_language="ru")
    assert updated_post_translation.id == original_post_translation.id
    assert updated_post_translation.translated_text == "[ru] aggiornato: Testo aggiornato lato nord"
    assert "Testo aggiornato lato nord" in post_update_calls

    comment_update_response = client.patch(
        f"/api/v1/comments/{comment.id}",
        data=json.dumps(
            {
                "text": "Commento aggiornato lato ponteggio",
                "source_language": "it",
                "remove_media_ids": [],
                "mentioned_profile_ids": [],
            }
        ),
        content_type="application/json",
        HTTP_X_EDILCLOUD_LOCALE="ru",
        **headers,
    )
    assert comment_update_response.status_code == 200
    updated_comment_translation = PostCommentTranslation.objects.get(comment=comment, target_language="ru")
    assert updated_comment_translation.id == original_comment_translation.id
    assert updated_comment_translation.translated_text == "[ru] aggiornato: Commento aggiornato lato ponteggio"
