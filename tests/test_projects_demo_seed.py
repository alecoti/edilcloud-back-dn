import json
from datetime import date
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostAttachment,
    PostCommentTranslation,
    PostKind,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectDocumentKind,
    ProjectDrawingPin,
    ProjectMember,
    ProjectPhoto,
    ProjectPost,
    ProjectPostTranslation,
    ProjectTask,
)
from edilcloud.modules.projects.demo_master_snapshot import build_demo_snapshot_payload
from edilcloud.modules.projects.services import (
    list_project_documents,
    list_project_drawings,
    list_project_recent_posts,
)
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
    assert ProjectDocument.objects.filter(project=project, document_kind=ProjectDocumentKind.DOCUMENT).exists()
    assert ProjectDocument.objects.filter(project=project, document_kind=ProjectDocumentKind.DRAWING).exists()
    assert ProjectPhoto.objects.filter(project=project).count() >= 2
    assert ProjectPost.objects.filter(project=project).count() >= 20
    assert PostAttachment.objects.filter(post__project=project).exists()
    assert CommentAttachment.objects.filter(comment__post__project=project).exists()
    assert ProjectDrawingPin.objects.filter(project=project, pin_code__gt="").exists()
    assert ProjectPost.objects.filter(project=project, post_kind=PostKind.ISSUE, alert=True).exists()
    assert ProjectPost.objects.filter(project=project, post_kind=PostKind.ISSUE, alert=False).exists()
    assert Profile.objects.filter(
        project_memberships__project=project,
        language="ro",
        email__in=[
            "bogdan.muresan@strutturenord.it",
            "alina.popescu@internibianchi.it",
        ],
    ).count() == 2
    assert Profile.objects.filter(
        project_memberships__project=project,
        language="fr",
        email="omar.elidrissi@auroracostruzioni.it",
    ).exists()
    assert ProjectPost.objects.filter(project=project, author__email="omar.elidrissi@auroracostruzioni.it", source_language="fr").exists()
    assert ProjectPost.objects.filter(project=project, author__email="bogdan.muresan@strutturenord.it", source_language="ro").exists()
    assert ProjectPostTranslation.objects.filter(post__project=project, target_language="it", post__source_language__in=["fr", "ro"]).exists()
    assert PostCommentTranslation.objects.filter(comment__post__project=project, target_language="it", comment__source_language__in=["fr", "ro"]).exists()

    documents_payload = list_project_documents(profile=viewer_profile, project_id=project.id)
    drawings_payload = list_project_drawings(profile=viewer_profile, project_id=project.id)
    recent_posts_payload = list_project_recent_posts(
        profile=viewer_profile,
        project_id=project.id,
        limit=100,
    )

    assert documents_payload
    assert drawings_payload
    assert all(item["document_kind"] == ProjectDocumentKind.DOCUMENT for item in documents_payload)
    assert all(item["document_kind"] == ProjectDocumentKind.DRAWING for item in drawings_payload)
    assert all(item["id"] not in {drawing["id"] for drawing in drawings_payload} for item in documents_payload)
    assert any(post["drawing_pin_tags"] for post in recent_posts_payload)
    assert any(
        any(tag["pin_code"] and tag["tag_text"] for tag in post["drawing_pin_tags"])
        for post in recent_posts_payload
    )


@pytest.mark.django_db
def test_demo_snapshot_payload_is_json_serializable(tmp_path, settings):
    settings.MEDIA_ROOT = Path(tmp_path) / "media"

    call_command("seed_rich_demo_project")

    project = Project.objects.get(name="Residenza Parco Naviglio - Lotto A")
    payload = build_demo_snapshot_payload(project=project, business_date=date(2026, 4, 12))

    serialized = json.dumps(payload)

    assert '"business_date": "2026-04-12"' in serialized


@pytest.mark.django_db
def test_seed_rich_demo_project_provisions_superuser_into_demo_workspace(tmp_path, settings):
    settings.MEDIA_ROOT = Path(tmp_path) / "media"

    user = get_user_model().objects.create_superuser(
        email="a.coti1987@gmail.com",
        password="demo1234!",
        first_name="Ale",
        last_name="Coti",
        language="it",
    )
    personal_workspace = Workspace.objects.create(
        name="Workspace Personale",
        email="a.coti1987@gmail.com",
        color="#0f172a",
    )
    Profile.objects.create(
        workspace=personal_workspace,
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name="Ale",
        last_name="Coti",
        language="it",
        position="Founder",
    )

    call_command("seed_rich_demo_project")

    project = Project.objects.get(name="Residenza Parco Naviglio - Lotto A")
    demo_profile = Profile.objects.get(workspace=project.workspace, user=user)

    assert demo_profile.email == "a.coti1987@gmail.com"
    assert demo_profile.role == WorkspaceRole.OWNER
    assert ProjectMember.objects.filter(
        project=project,
        profile=demo_profile,
        role=WorkspaceRole.OWNER,
    ).exists()
