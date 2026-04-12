import json
from datetime import date
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostAttachment,
    PostKind,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectMember,
    ProjectPhoto,
    ProjectPost,
    ProjectTask,
)
from edilcloud.modules.projects.demo_master_snapshot import build_demo_snapshot_payload
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole


@pytest.mark.django_db
def test_seed_rich_demo_project_creates_accessible_realistic_project(tmp_path, settings):
    settings.MEDIA_ROOT = Path(tmp_path) / "media"

    user = get_user_model().objects.create_user(
        email="viewer.local@example.com",
        password="demo1234!",
        first_name="Andrea",
        last_name="Local",
        language="it",
    )
    workspace = Workspace.objects.create(
        name="Viewer Workspace",
        email="viewer.local@example.com",
        color="#334155",
    )
    viewer_profile = Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name="Andrea",
        last_name="Local",
        language="it",
        position="Viewer locale",
    )

    call_command(
        "seed_rich_demo_project",
        viewer_email="viewer.local@example.com",
        viewer_password="demo1234!",
    )
    call_command(
        "seed_rich_demo_project",
        viewer_email="viewer.local@example.com",
        viewer_password="demo1234!",
    )

    project = Project.objects.get(name="Residenza Parco Naviglio - Lotto A")

    assert Project.objects.filter(name="Residenza Parco Naviglio - Lotto A").count() == 1
    assert ProjectMember.objects.filter(project=project, profile=viewer_profile).exists()
    assert project.latitude is not None
    assert project.longitude is not None
    assert ProjectTask.objects.filter(project=project).count() >= 6
    assert ProjectActivity.objects.filter(task__project=project).count() >= 18
    assert ProjectDocument.objects.filter(project=project).count() >= 3
    assert ProjectPhoto.objects.filter(project=project).count() >= 2
    assert ProjectPost.objects.filter(project=project).count() >= 20
    assert PostAttachment.objects.filter(post__project=project).exists()
    assert CommentAttachment.objects.filter(comment__post__project=project).exists()
    assert ProjectPost.objects.filter(project=project, post_kind=PostKind.ISSUE, alert=True).exists()
    assert ProjectPost.objects.filter(project=project, post_kind=PostKind.ISSUE, alert=False).exists()


@pytest.mark.django_db
def test_demo_snapshot_payload_is_json_serializable(tmp_path, settings):
    settings.MEDIA_ROOT = Path(tmp_path) / "media"

    call_command("seed_rich_demo_project")

    project = Project.objects.get(name="Residenza Parco Naviglio - Lotto A")
    payload = build_demo_snapshot_payload(project=project, business_date=date(2026, 4, 12))

    serialized = json.dumps(payload)

    assert '"business_date": "2026-04-12"' in serialized
