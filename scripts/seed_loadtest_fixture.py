from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edilcloud.settings.local")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.hashers import make_password  # noqa: E402
from django.core.files.base import ContentFile  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from edilcloud.modules.projects.models import (  # noqa: E402
    PostComment,
    PostKind,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectFolder,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPost,
    ProjectTask,
    TaskActivityStatus,
)
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed a realistic workspace/project fixture for frontend API load testing.",
    )
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--password", default="devpass123")
    parser.add_argument("--workspace-name", default="Load Test Company")
    parser.add_argument("--project-name", default="Load Test Platform Scale")
    parser.add_argument("--email-prefix", default="loadtest.user")
    return parser.parse_args()


def build_email(prefix: str, index: int) -> str:
    return f"{prefix}.{index:04d}@example.com"


def ensure_user(
    *,
    email: str,
    password_hash: str,
    first_name: str,
    last_name: str,
):
    user_model = get_user_model()
    username = email.split("@", 1)[0]
    user, created = user_model.objects.get_or_create(
        email=email,
        defaults={
            "username": username[:150],
            "password": password_hash,
            "first_name": first_name,
            "last_name": last_name,
            "language": "it",
            "is_active": True,
        },
    )
    changed = False
    if not created and user.password != password_hash:
        user.password = password_hash
        changed = True
    if user.username != username[:150]:
        user.username = username[:150]
        changed = True
    if user.first_name != first_name:
        user.first_name = first_name
        changed = True
    if user.last_name != last_name:
        user.last_name = last_name
        changed = True
    if getattr(user, "language", "it") != "it":
        user.language = "it"
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if changed:
        user.save()
    return user


def ensure_profile(*, workspace: Workspace, user, role: str, position: str = ""):
    profile, _created = Profile.objects.get_or_create(
        workspace=workspace,
        user=user,
        defaults={
            "email": user.email,
            "role": role,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "language": getattr(user, "language", "it") or "it",
            "position": position,
            "is_active": True,
        },
    )
    changed = False
    if profile.email != user.email:
        profile.email = user.email
        changed = True
    if profile.role != role:
        profile.role = role
        changed = True
    if profile.first_name != user.first_name:
        profile.first_name = user.first_name
        changed = True
    if profile.last_name != user.last_name:
        profile.last_name = user.last_name
        changed = True
    if profile.language != (getattr(user, "language", "it") or "it"):
        profile.language = getattr(user, "language", "it") or "it"
        changed = True
    if profile.position != position:
        profile.position = position
        changed = True
    if not profile.is_active:
        profile.is_active = True
        changed = True
    if changed:
        profile.save()
    return profile


def ensure_member(*, project: Project, profile: Profile, role: str):
    member, _created = ProjectMember.objects.get_or_create(
        project=project,
        profile=profile,
        defaults={
            "role": role,
            "status": ProjectMemberStatus.ACTIVE,
            "disabled": False,
            "is_external": False,
        },
    )
    changed = False
    if member.role != role:
        member.role = role
        changed = True
    if member.status != ProjectMemberStatus.ACTIVE:
        member.status = ProjectMemberStatus.ACTIVE
        changed = True
    if member.disabled:
        member.disabled = False
        changed = True
    if member.is_external:
        member.is_external = False
        changed = True
    if changed:
        member.save()
    return member


def ensure_project_content(*, project: Project, owner_profile: Profile, worker_profiles: list[Profile]):
    if project.tasks.exists():
        return

    docs_folder = ProjectFolder.objects.create(
        project=project,
        name="Documenti Tecnici",
        path="documenti-tecnici",
    )
    reports_folder = ProjectFolder.objects.create(
        project=project,
        name="Rapportini",
        path="rapportini",
    )

    for index in range(1, 4):
        ProjectDocument.objects.create(
            project=project,
            folder=docs_folder if index < 3 else reports_folder,
            title=f"Documento load test {index}",
            description="Documento di esempio per il benchmark locale.",
            document=ContentFile(
                f"Documento load test {index}\nContenuto sintetico per il benchmark.\n".encode("utf-8"),
                name=f"load-test-{index}.txt",
            ),
        )

    today = date.today()
    now = timezone.now()
    activity_status_cycle = [
        TaskActivityStatus.TODO,
        TaskActivityStatus.PROGRESS,
        TaskActivityStatus.COMPLETED,
    ]

    usable_workers = worker_profiles[: max(1, min(len(worker_profiles), 12))]
    for task_index in range(1, 13):
        task = ProjectTask.objects.create(
            project=project,
            name=f"Task load test {task_index}",
            assigned_company=project.workspace,
            date_start=today + timedelta(days=task_index - 1),
            date_end=today + timedelta(days=task_index + 2),
            progress=(task_index * 7) % 100,
            alert=task_index % 4 == 0,
            starred=task_index % 5 == 0,
            note="Task seedato per i benchmark di piattaforma.",
        )

        for activity_index in range(1, 3):
            worker = usable_workers[(task_index + activity_index - 2) % len(usable_workers)]
            activity_start = timezone.make_aware(
                datetime.combine(today + timedelta(days=task_index - 1), time(hour=8 + activity_index)),
            )
            activity_end = activity_start + timedelta(hours=2)
            activity = ProjectActivity.objects.create(
                task=task,
                title=f"Attivita {task_index}.{activity_index}",
                description="Attivita operativa seedata per i test di carico.",
                status=activity_status_cycle[(task_index + activity_index) % len(activity_status_cycle)],
                datetime_start=activity_start,
                datetime_end=activity_end,
                alert=activity_index == 2 and task_index % 3 == 0,
                note="Nota operativa di esempio.",
            )
            activity.workers.add(owner_profile, worker)

            if task_index <= 6 and activity_index == 1:
                post = ProjectPost.objects.create(
                    project=project,
                    task=task,
                    activity=activity,
                    author=worker,
                    post_kind=PostKind.ISSUE if task_index % 2 == 0 else PostKind.WORK_PROGRESS,
                    text=f"Aggiornamento load test {task_index}: stato attivita e criticita aperte.",
                    original_text=f"Aggiornamento load test {task_index}: stato attivita e criticita aperte.",
                    alert=task_index % 2 == 0,
                    is_public=False,
                    published_date=now - timedelta(minutes=task_index * 4),
                    weather_snapshot={"summary": "sereno", "temperature_c": 18 + task_index},
                )
                PostComment.objects.create(
                    post=post,
                    author=owner_profile,
                    text=f"Commento di coordinamento {task_index}.",
                    original_text=f"Commento di coordinamento {task_index}.",
                )


@transaction.atomic
def main() -> int:
    args = parse_args()
    if args.users <= 0:
        raise SystemExit("--users deve essere maggiore di zero.")

    password_hash = make_password(args.password)
    user_model = get_user_model()
    owner_email = f"{args.email_prefix}.owner@example.com"
    workspace, _created = Workspace.objects.get_or_create(
        name=args.workspace_name,
        defaults={
            "email": "loadtest@example.com",
            "phone": "+390200000001",
            "workspace_type": "impresa",
            "description": "Workspace seedato per benchmark e capacity planning locale.",
            "is_active": True,
        },
    )
    if not workspace.is_active:
        workspace.is_active = True
        workspace.save(update_fields=["is_active", "updated_at"])

    project, created = Project.objects.get_or_create(
        workspace=workspace,
        name=args.project_name,
        defaults={
            "description": "Progetto seedato per benchmark di frontend API e capacity planning.",
            "address": "Via Torino 42, Milano",
            "latitude": 45.4642,
            "longitude": 9.19,
            "date_start": date.today(),
            "date_end": date.today() + timedelta(days=120),
            "status": 1,
        },
    )
    desired_users: list[tuple[str, str, str, str]] = [
        (owner_email, "loadtest.owner", "Load", "Owner"),
        *[
            (
                build_email(args.email_prefix, index),
                f"{args.email_prefix}.{index:04d}"[:150],
                "Load",
                f"User {index:04d}",
            )
            for index in range(1, args.users + 1)
        ],
    ]
    desired_emails = [email for email, _username, _first_name, _last_name in desired_users]
    existing_users = {
        user.email: user
        for user in user_model.objects.filter(email__in=desired_emails)
    }

    users_to_create = []
    users_to_update = []
    for email, username, first_name, last_name in desired_users:
        user = existing_users.get(email)
        if user is None:
            users_to_create.append(
                user_model(
                    email=email,
                    username=username,
                    password=password_hash,
                    first_name=first_name,
                    last_name=last_name,
                    language="it",
                    is_active=True,
                )
            )
            continue

        changed = False
        if user.username != username:
            user.username = username
            changed = True
        if user.password != password_hash:
            user.password = password_hash
            changed = True
        if user.first_name != first_name:
            user.first_name = first_name
            changed = True
        if user.last_name != last_name:
            user.last_name = last_name
            changed = True
        if getattr(user, "language", "it") != "it":
            user.language = "it"
            changed = True
        if not user.is_active:
            user.is_active = True
            changed = True
        if changed:
            users_to_update.append(user)

    if users_to_create:
        user_model.objects.bulk_create(users_to_create, batch_size=500)
    if users_to_update:
        user_model.objects.bulk_update(
            users_to_update,
            ["username", "password", "first_name", "last_name", "language", "is_active"],
            batch_size=500,
        )

    users_by_email = {
        user.email: user
        for user in user_model.objects.filter(email__in=desired_emails)
    }
    owner_user = users_by_email[owner_email]

    existing_profiles = {
        profile.user_id: profile
        for profile in Profile.objects.filter(workspace=workspace, user_id__in=[user.id for user in users_by_email.values()])
    }
    profiles_to_create = []
    profiles_to_update = []
    for email, _username, first_name, last_name in desired_users:
        user = users_by_email[email]
        role = WorkspaceRole.OWNER if email == owner_email else WorkspaceRole.WORKER
        position = "Responsabile piattaforma" if email == owner_email else "Operatore di cantiere"
        profile = existing_profiles.get(user.id)
        if profile is None:
            profiles_to_create.append(
                Profile(
                    workspace=workspace,
                    user=user,
                    email=user.email,
                    role=role,
                    first_name=first_name,
                    last_name=last_name,
                    language="it",
                    position=position,
                    is_active=True,
                )
            )
            continue

        changed = False
        if profile.email != user.email:
            profile.email = user.email
            changed = True
        if profile.role != role:
            profile.role = role
            changed = True
        if profile.first_name != first_name:
            profile.first_name = first_name
            changed = True
        if profile.last_name != last_name:
            profile.last_name = last_name
            changed = True
        if profile.language != "it":
            profile.language = "it"
            changed = True
        if profile.position != position:
            profile.position = position
            changed = True
        if not profile.is_active:
            profile.is_active = True
            changed = True
        if changed:
            profiles_to_update.append(profile)

    if profiles_to_create:
        Profile.objects.bulk_create(profiles_to_create, batch_size=500)
    if profiles_to_update:
        Profile.objects.bulk_update(
            profiles_to_update,
            ["email", "role", "first_name", "last_name", "language", "position", "is_active"],
            batch_size=500,
        )

    profiles_by_email = {
        profile.email: profile
        for profile in Profile.objects.filter(workspace=workspace, email__in=desired_emails)
    }
    owner_profile = profiles_by_email[owner_email]

    if project.created_by_id is None:
        project.created_by = owner_profile
        project.save(update_fields=["created_by", "updated_at"])

    existing_members = {
        member.profile_id: member
        for member in ProjectMember.objects.filter(
            project=project,
            profile_id__in=[profile.id for profile in profiles_by_email.values()],
        )
    }
    members_to_create = []
    members_to_update = []
    for email in desired_emails:
        profile = profiles_by_email[email]
        role = WorkspaceRole.OWNER if email == owner_email else WorkspaceRole.WORKER
        member = existing_members.get(profile.id)
        if member is None:
            members_to_create.append(
                ProjectMember(
                    project=project,
                    profile=profile,
                    role=role,
                    status=ProjectMemberStatus.ACTIVE,
                    disabled=False,
                    is_external=False,
                )
            )
            continue

        changed = False
        if member.role != role:
            member.role = role
            changed = True
        if member.status != ProjectMemberStatus.ACTIVE:
            member.status = ProjectMemberStatus.ACTIVE
            changed = True
        if member.disabled:
            member.disabled = False
            changed = True
        if member.is_external:
            member.is_external = False
            changed = True
        if changed:
            members_to_update.append(member)

    if members_to_create:
        ProjectMember.objects.bulk_create(members_to_create, batch_size=500)
    if members_to_update:
        ProjectMember.objects.bulk_update(
            members_to_update,
            ["role", "status", "disabled", "is_external"],
            batch_size=500,
        )

    worker_profiles = [
        profile
        for email, profile in profiles_by_email.items()
        if email != owner_email
    ]
    created_users = len(users_to_create)

    ensure_project_content(project=project, owner_profile=owner_profile, worker_profiles=worker_profiles)

    summary = {
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        "project_id": project.id,
        "project_name": project.name,
        "user_count": args.users,
        "created_users": created_users,
        "password": args.password,
        "owner_email": owner_user.email,
        "sample_worker_email": build_email(args.email_prefix, 1),
        "generated_at": timezone.now().isoformat(),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
