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
from django.utils import timezone  # noqa: E402

from edilcloud.modules.notifications.models import Notification  # noqa: E402
from edilcloud.modules.projects.models import (  # noqa: E402
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPost,
    ProjectTask,
    ProjectFolder,
    TaskActivityStatus,
)
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole  # noqa: E402


WORKSPACE_NAME = "Smoke Notifications Workspace"
PROJECT_NAME = "Smoke Notifications Realtime"
TASK_NAME = "Coordinamento realtime di cantiere"
ACTIVITY_TITLE = "Verifica corridoio nord"

SENDER_EMAIL = "notify.sender@example.com"
SENDER_PASSWORD = "devpass123"
RECIPIENT_EMAIL = "notify.recipient@example.com"
RECIPIENT_PASSWORD = "devpass123"


def ensure_user(*, email: str, password: str, first_name: str, last_name: str):
    user_model = get_user_model()
    user, _created = user_model.objects.get_or_create(
        email=email,
        defaults={
            "username": email.split("@")[0],
            "first_name": first_name,
            "last_name": last_name,
            "language": "it",
        },
    )
    user.username = user.username or email.split("@")[0]
    user.first_name = first_name
    user.last_name = last_name
    user.language = "it"
    user.set_password(password)
    user.save()
    return user


def ensure_profile(
    *,
    workspace: Workspace,
    user,
    role: str,
    first_name: str,
    last_name: str,
    position: str,
):
    profile, _created = Profile.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={
            "email": user.email,
            "role": role,
            "first_name": first_name,
            "last_name": last_name,
            "language": "it",
            "position": position,
            "is_active": True,
        },
    )
    profile.email = user.email
    profile.role = role
    profile.first_name = first_name
    profile.last_name = last_name
    profile.language = "it"
    profile.position = position
    profile.is_active = True
    profile.save()
    return profile


def ensure_project_member(*, project: Project, profile: Profile, role: str):
    ProjectMember.objects.update_or_create(
        project=project,
        profile=profile,
        defaults={
            "role": role,
            "status": ProjectMemberStatus.ACTIVE,
            "disabled": False,
            "is_external": profile.workspace_id != project.workspace_id,
        },
    )


def reset_smoke_project(project: Project) -> None:
    Notification.objects.filter(recipient_profile__workspace=project.workspace, recipient_profile__user__email=RECIPIENT_EMAIL).delete()
    Notification.objects.filter(recipient_profile__workspace=project.workspace, recipient_profile__user__email=SENDER_EMAIL).delete()
    ProjectPost.objects.filter(project=project).delete()
    ProjectDocument.objects.filter(project=project).delete()
    ProjectFolder.objects.filter(project=project, is_root=False).delete()


def main() -> int:
    workspace, _created = Workspace.objects.get_or_create(
        name=WORKSPACE_NAME,
        defaults={"email": "smoke-notifications@example.com"},
    )
    workspace.email = workspace.email or "smoke-notifications@example.com"
    workspace.is_active = True
    workspace.save()

    sender_user = ensure_user(
        email=SENDER_EMAIL,
        password=SENDER_PASSWORD,
        first_name="Marco",
        last_name="Carminati",
    )
    recipient_user = ensure_user(
        email=RECIPIENT_EMAIL,
        password=RECIPIENT_PASSWORD,
        first_name="Alessandro",
        last_name="Coti",
    )

    sender_profile = ensure_profile(
        workspace=workspace,
        user=sender_user,
        role=WorkspaceRole.OWNER,
        first_name="Marco",
        last_name="Carminati",
        position="Direttore tecnico",
    )
    recipient_profile = ensure_profile(
        workspace=workspace,
        user=recipient_user,
        role=WorkspaceRole.MANAGER,
        first_name="Alessandro",
        last_name="Coti",
        position="Project manager",
    )

    project, _created = Project.objects.get_or_create(
        workspace=workspace,
        name=PROJECT_NAME,
        defaults={
            "created_by": sender_profile,
            "description": "Seed dedicato per smoke test notifiche e realtime.",
            "address": "Via Torino 42, Milano",
            "date_start": date.today(),
            "date_end": date.today() + timedelta(days=30),
        },
    )
    project.created_by = sender_profile
    project.description = "Seed dedicato per smoke test notifiche e realtime."
    project.address = "Via Torino 42, Milano"
    project.date_start = project.date_start or date.today()
    project.date_end = project.date_end or (date.today() + timedelta(days=30))
    project.save()

    ensure_project_member(project=project, profile=sender_profile, role=WorkspaceRole.OWNER)
    ensure_project_member(project=project, profile=recipient_profile, role=WorkspaceRole.MANAGER)

    task, _created = ProjectTask.objects.get_or_create(
        project=project,
        name=TASK_NAME,
        defaults={
            "assigned_company": workspace,
            "date_start": date.today(),
            "date_end": date.today() + timedelta(days=10),
            "progress": 20,
            "status": 1,
            "alert": False,
            "starred": False,
            "note": "Task smoke per verificare feed live e notifiche.",
        },
    )
    task.assigned_company = workspace
    task.date_start = task.date_start or date.today()
    task.date_end = task.date_end or (date.today() + timedelta(days=10))
    task.progress = 20
    task.status = 1
    task.alert = False
    task.starred = False
    task.note = "Task smoke per verificare feed live e notifiche."
    task.save()

    activity, _created = ProjectActivity.objects.get_or_create(
        task=task,
        title=ACTIVITY_TITLE,
        defaults={
            "description": "Attivita dedicata allo smoke test browser di notifiche e realtime.",
            "status": TaskActivityStatus.PROGRESS,
            "datetime_start": timezone.now(),
            "datetime_end": timezone.now() + timedelta(hours=4),
            "alert": False,
            "starred": False,
            "note": "Tenere pulita per verifiche deterministiche.",
        },
    )
    activity.description = "Attivita dedicata allo smoke test browser di notifiche e realtime."
    activity.status = TaskActivityStatus.PROGRESS
    activity.datetime_start = activity.datetime_start or timezone.now()
    activity.datetime_end = activity.datetime_end or (timezone.now() + timedelta(hours=4))
    activity.alert = False
    activity.starred = False
    activity.note = "Tenere pulita per verifiche deterministiche."
    activity.save()
    activity.workers.set([sender_profile, recipient_profile])

    reset_smoke_project(project)

    print(
        json.dumps(
            {
                "workspace": {"id": workspace.id, "name": workspace.name},
                "project": {"id": project.id, "name": project.name},
                "task": {"id": task.id, "name": task.name},
                "activity": {"id": activity.id, "title": activity.title},
                "sender": {
                    "email": SENDER_EMAIL,
                    "password": SENDER_PASSWORD,
                    "profile_id": sender_profile.id,
                },
                "recipient": {
                    "email": RECIPIENT_EMAIL,
                    "password": RECIPIENT_PASSWORD,
                    "profile_id": recipient_profile.id,
                },
            },
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
