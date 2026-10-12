import json
from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from edilcloud.modules.projects.models import (
    Project,
    ProjectDocument,
    ProjectFolder,
    ProjectMember,
    ProjectMemberStatus,
    ProjectOperationalEvent,
)
from edilcloud.modules.workspaces.models import WorkspaceRole
from tests.test_projects_api import auth_headers, create_workspace_profile


@pytest.fixture
def document_project():
    _user, _workspace, profile = create_workspace_profile(
        email="folder.uploads@example.com", password="devpass123"
    )
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Folder upload regression",
        date_start=date.today(),
        date_end=date.today() + timedelta(days=15),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    client = Client()
    headers = auth_headers(client, email=profile.email, password="devpass123")
    return project, client, headers


@pytest.mark.django_db
def test_repeated_folder_creation_reuses_id_and_preserves_visibility(document_project):
    project, client, headers = document_project
    endpoint = f"/api/v1/projects/{project.id}/folders"
    first = client.post(
        endpoint,
        data=json.dumps({"name": "STRUCTURAL", "is_public": False}),
        content_type="application/json",
        **headers,
    )
    repeated = client.post(
        endpoint,
        data=json.dumps({"name": "STRUCTURAL", "is_public": True}),
        content_type="application/json",
        **headers,
    )
    assert first.status_code == repeated.status_code == 201
    assert first.json()["id"] == repeated.json()["id"]
    assert not repeated.json()["is_public"]
    assert ProjectFolder.objects.filter(project=project).count() == 1
    assert ProjectOperationalEvent.objects.filter(
        project=project, event_type="folder.created"
    ).count() == 1


@pytest.mark.django_db
def test_batch_upload_reuses_nested_paths_and_keeps_every_file(document_project, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    project, client, headers = document_project
    for index in range(16):
        response = client.post(
            f"/api/v1/projects/{project.id}/documents",
            data={
                "additional_path": "STRUCTURAL/TEKLA-STRUCTURES",
                "document": SimpleUploadedFile(
                    f"building-permit-{index}.zip", b"PK\x05\x06" + bytes(18),
                    content_type="application/zip",
                ),
            },
            **headers,
        )
        assert response.status_code == 201, response.content
    assert list(
        ProjectFolder.objects.filter(project=project).order_by("path").values_list("path", flat=True)
    ) == ["STRUCTURAL", "STRUCTURAL/TEKLA-STRUCTURES"]
    assert ProjectDocument.objects.filter(
        project=project, folder__path="STRUCTURAL/TEKLA-STRUCTURES"
    ).count() == 16
