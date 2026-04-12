from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path


def bootstrap_django() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    src_root = repo_root / "src"
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edilcloud.settings.local")

    import django

    django.setup()


bootstrap_django()

from django.contrib.auth import get_user_model  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.utils import timezone  # noqa: E402

from edilcloud.modules.projects.models import (  # noqa: E402
    PostKind,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectFolder,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPhoto,
    ProjectPost,
    ProjectTask,
)
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole  # noqa: E402


DEFAULT_PASSWORD = "devpass123"
PRIMARY_WORKSPACE_NAME = "Smoke Project Core Workspace"
SUPPLIER_WORKSPACE_NAME = "Smoke Project Core Supplier"
PROJECT_NAME = "Smoke Project Detail Core"

OWNER_EMAIL = "project.detail.owner@example.com"
DELEGATE_EMAIL = "project.detail.delegate@example.com"
WORKER_EMAIL = "project.detail.worker@example.com"
SUPPLIER_EMAIL = "project.detail.supplier@example.com"


def ensure_user(*, email: str, username: str, first_name: str, last_name: str):
    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        email=email,
        defaults={
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
            "language": "it",
            "is_active": True,
        },
    )
    user.username = user.username or username
    user.first_name = first_name
    user.last_name = last_name
    user.language = getattr(user, "language", "it") or "it"
    user.is_active = True
    user.set_password(DEFAULT_PASSWORD)
    user.save()
    return user


def create_profile(
    *,
    workspace: Workspace,
    user,
    role: str,
    first_name: str,
    last_name: str,
    position: str,
) -> Profile:
    return Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=role,
        first_name=first_name,
        last_name=last_name,
        language="it",
        position=position,
        phone="+39 333 000 0000",
        is_active=True,
    )


def main() -> int:
    primary_workspace, _ = Workspace.objects.get_or_create(
        name=PRIMARY_WORKSPACE_NAME,
        defaults={"email": OWNER_EMAIL, "is_active": True},
    )
    primary_workspace.email = primary_workspace.email or OWNER_EMAIL
    primary_workspace.is_active = True
    primary_workspace.save()

    supplier_workspace, _ = Workspace.objects.get_or_create(
        name=SUPPLIER_WORKSPACE_NAME,
        defaults={"email": SUPPLIER_EMAIL, "is_active": True},
    )
    supplier_workspace.email = supplier_workspace.email or SUPPLIER_EMAIL
    supplier_workspace.is_active = True
    supplier_workspace.save()

    owner_user = ensure_user(
        email=OWNER_EMAIL,
        username="project-detail-owner",
        first_name="Olivia",
        last_name="Rinaldi",
    )
    delegate_user = ensure_user(
        email=DELEGATE_EMAIL,
        username="project-detail-delegate",
        first_name="Diego",
        last_name="Martini",
    )
    worker_user = ensure_user(
        email=WORKER_EMAIL,
        username="project-detail-worker",
        first_name="Walter",
        last_name="Serra",
    )
    supplier_user = ensure_user(
        email=SUPPLIER_EMAIL,
        username="project-detail-supplier",
        first_name="Sara",
        last_name="Conti",
    )

    Profile.objects.filter(user__email__in=[OWNER_EMAIL, DELEGATE_EMAIL, WORKER_EMAIL], workspace=primary_workspace).delete()
    Profile.objects.filter(user__email=SUPPLIER_EMAIL, workspace=supplier_workspace).delete()

    owner_profile = create_profile(
        workspace=primary_workspace,
        user=owner_user,
        role=WorkspaceRole.OWNER,
        first_name="Olivia",
        last_name="Rinaldi",
        position="Owner di commessa",
    )
    delegate_profile = create_profile(
        workspace=primary_workspace,
        user=delegate_user,
        role=WorkspaceRole.DELEGATE,
        first_name="Diego",
        last_name="Martini",
        position="Delegato operativo",
    )
    worker_profile = create_profile(
        workspace=primary_workspace,
        user=worker_user,
        role=WorkspaceRole.WORKER,
        first_name="Walter",
        last_name="Serra",
        position="Operativo di cantiere",
    )
    supplier_profile = create_profile(
        workspace=supplier_workspace,
        user=supplier_user,
        role=WorkspaceRole.WORKER,
        first_name="Sara",
        last_name="Conti",
        position="Fornitore esterno",
    )

    project, _ = Project.objects.get_or_create(
        workspace=primary_workspace,
        name=PROJECT_NAME,
        defaults={
            "created_by": owner_profile,
            "description": "Progetto smoke per audit detail core",
            "address": "Via Torino 42, Milano",
            "google_place_id": "smoke-project-detail-core-place",
            "latitude": 45.461404,
            "longitude": 9.185167,
            "date_start": date.today(),
            "date_end": date.today() + timedelta(days=30),
        },
    )
    project.created_by = owner_profile
    project.description = "Progetto smoke per audit detail core"
    project.address = "Via Torino 42, Milano"
    project.google_place_id = "smoke-project-detail-core-place"
    project.latitude = 45.461404
    project.longitude = 9.185167
    project.date_start = date.today()
    project.date_end = date.today() + timedelta(days=30)
    project.status = 1
    project.save()

    ProjectPost.objects.filter(project=project).delete()
    ProjectDocument.objects.filter(project=project).delete()
    ProjectPhoto.objects.filter(project=project).delete()
    ProjectFolder.objects.filter(project=project).delete()
    ProjectMember.objects.filter(project=project).delete()
    ProjectTask.objects.filter(project=project).delete()

    ProjectMember.objects.create(
        project=project,
        profile=owner_profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
        is_external=False,
        project_invitation_date=timezone.now(),
    )
    ProjectMember.objects.create(
        project=project,
        profile=delegate_profile,
        role=WorkspaceRole.DELEGATE,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
        is_external=False,
        project_invitation_date=timezone.now(),
    )
    ProjectMember.objects.create(
        project=project,
        profile=worker_profile,
        role=WorkspaceRole.WORKER,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
        is_external=False,
        project_invitation_date=timezone.now(),
    )
    ProjectMember.objects.create(
        project=project,
        profile=supplier_profile,
        role=WorkspaceRole.WORKER,
        status=ProjectMemberStatus.ACTIVE,
        disabled=False,
        is_external=True,
        project_invitation_date=timezone.now(),
    )

    task = ProjectTask.objects.create(
        project=project,
        name="Coordinamento impianti piano terra",
        assigned_company=supplier_workspace,
        date_start=date.today(),
        date_end=date.today() + timedelta(days=12),
        progress=45,
        note="Verifica interferenze impianti e chiusure cavedi",
        alert=True,
        starred=True,
    )
    activity = ProjectActivity.objects.create(
        task=task,
        title="Sopralluogo tecnico corridoio nord",
        description="Controllo quote, cavedi e predisposizioni",
        status="progress",
        datetime_start=timezone.now(),
        datetime_end=timezone.now() + timedelta(hours=4),
        note="Serve conferma definitiva sui passaggi impiantistici",
        alert=True,
        starred=True,
    )
    activity.workers.set([delegate_profile, worker_profile, supplier_profile])

    ProjectPost.objects.create(
        project=project,
        task=task,
        activity=activity,
        author=owner_profile,
        post_kind=PostKind.ISSUE,
        text="Chiusura cavedi lato nord non confermata. Serve verifica in campo e conferma DL prima di chiudere il fronte.",
        original_text="Chiusura cavedi lato nord non confermata. Serve verifica in campo e conferma DL prima di chiudere il fronte.",
        source_language="it",
        display_language="it",
        alert=True,
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
        title="Verbale coordinamento PT",
        description="Verbale tecnico del sopralluogo corridoio nord",
        document=SimpleUploadedFile(
            "verbale-coordinamento-pt.pdf",
            b"%PDF-1.4 smoke project detail core",
            content_type="application/pdf",
        ),
    )
    ProjectPhoto.objects.create(
        project=project,
        title="Panoramica corridoio nord",
        photo=SimpleUploadedFile(
            "corridoio-nord.png",
            b"fake-image",
            content_type="image/png",
        ),
    )

    print(
        json.dumps(
            {
                "projectId": project.id,
                "projectName": project.name,
                "owner": {
                    "email": OWNER_EMAIL,
                    "password": DEFAULT_PASSWORD,
                    "profileId": owner_profile.id,
                },
                "worker": {
                    "email": WORKER_EMAIL,
                    "password": DEFAULT_PASSWORD,
                    "profileId": worker_profile.id,
                },
                "teamProfileIds": {
                    "owner": owner_profile.id,
                    "delegate": delegate_profile.id,
                    "worker": worker_profile.id,
                    "supplier": supplier_profile.id,
                },
                "taskId": task.id,
                "activityId": activity.id,
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
