from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
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

from edilcloud.modules.projects.models import (  # noqa: E402
    PostComment,
    PostKind,
    Project,
    ProjectActivity,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPost,
    ProjectPostSeenState,
    ProjectTask,
    TaskActivityStatus,
)
from edilcloud.modules.workspaces.models import Workspace, WorkspaceRole  # noqa: E402


SENDER_EMAIL = "feed.sender@example.com"
RECIPIENT_EMAIL = "feed.recipient@example.com"
DEFAULT_PASSWORD = "devpass123"
WORKSPACE_NAME = "Smoke Feed Workspace"
PROJECT_NAME = "Smoke Feed Experience"
TASK_NAME = "Coordinamento feed operativo"
ACTIVITY_TITLE = "Sopralluogo e aggiornamenti realtime"


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
    if created:
        user.set_password(DEFAULT_PASSWORD)
    else:
        user.username = user.username or username
        user.first_name = first_name
        user.last_name = last_name
        user.language = getattr(user, "language", "it") or "it"
        user.is_active = True
        user.set_password(DEFAULT_PASSWORD)
    user.save()
    return user


def ensure_profile(workspace: Workspace, *, user, role: str, first_name: str, last_name: str):
    profile, _created = workspace.profiles.get_or_create(
        user=user,
        defaults={
            "email": user.email,
            "role": role,
            "first_name": first_name,
            "last_name": last_name,
            "language": "it",
        },
    )
    profile.email = user.email
    profile.role = role
    profile.first_name = first_name
    profile.last_name = last_name
    profile.language = profile.language or "it"
    profile.is_default = True
    profile.save()
    return profile


def ensure_project_member(project: Project, profile, role: str):
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
    member.role = role
    member.status = ProjectMemberStatus.ACTIVE
    member.disabled = False
    member.is_external = False
    member.save()
    return member


def main():
    sender_user = ensure_user(
        email=SENDER_EMAIL,
        username="feed-sender",
        first_name="Marco",
        last_name="Carminati",
    )
    recipient_user = ensure_user(
        email=RECIPIENT_EMAIL,
        username="feed-recipient",
        first_name="Alessandro",
        last_name="Coti",
    )

    workspace, _created = Workspace.objects.get_or_create(
        name=WORKSPACE_NAME,
        defaults={"email": SENDER_EMAIL, "is_active": True},
    )
    workspace.email = workspace.email or SENDER_EMAIL
    workspace.is_active = True
    workspace.save()

    sender_profile = ensure_profile(
        workspace,
        user=sender_user,
        role=WorkspaceRole.OWNER,
        first_name="Marco",
        last_name="Carminati",
    )
    recipient_profile = ensure_profile(
        workspace,
        user=recipient_user,
        role=WorkspaceRole.MANAGER,
        first_name="Alessandro",
        last_name="Coti",
    )

    today = timezone.localdate()
    project, _created = Project.objects.get_or_create(
        workspace=workspace,
        name=PROJECT_NAME,
        defaults={
            "created_by": sender_profile,
            "description": "Dataset smoke per feed operativo e infinite loading.",
            "address": "Via Torino 42, Milano",
            "date_start": today - timedelta(days=14),
            "date_end": today + timedelta(days=45),
        },
    )
    project.created_by = sender_profile
    project.description = "Dataset smoke per feed operativo e infinite loading."
    project.address = "Via Torino 42, Milano"
    project.date_start = project.date_start or (today - timedelta(days=14))
    project.date_end = project.date_end or (today + timedelta(days=45))
    project.save()

    ensure_project_member(project, sender_profile, WorkspaceRole.OWNER)
    ensure_project_member(project, recipient_profile, WorkspaceRole.MANAGER)

    task, _created = ProjectTask.objects.get_or_create(
        project=project,
        name=TASK_NAME,
        defaults={
            "date_start": today - timedelta(days=7),
            "date_end": today + timedelta(days=14),
            "progress": 48,
            "note": "Task smoke dedicato al feed.",
        },
    )
    task.date_start = task.date_start or (today - timedelta(days=7))
    task.date_end = task.date_end or (today + timedelta(days=14))
    task.progress = 48
    task.note = "Task smoke dedicato al feed."
    task.save()

    activity, _created = ProjectActivity.objects.get_or_create(
        task=task,
        title=ACTIVITY_TITLE,
        defaults={
            "status": TaskActivityStatus.PROGRESS,
            "datetime_start": timezone.now() - timedelta(days=1, hours=3),
            "datetime_end": timezone.now() + timedelta(hours=8),
            "description": "Attivita smoke per verifiche realtime del feed.",
            "note": "Usata per testare jump, unread e scroll progressivo.",
        },
    )
    activity.status = TaskActivityStatus.PROGRESS
    activity.datetime_start = activity.datetime_start or (timezone.now() - timedelta(days=1, hours=3))
    activity.datetime_end = activity.datetime_end or (timezone.now() + timedelta(hours=8))
    activity.description = "Attivita smoke per verifiche realtime del feed."
    activity.note = "Usata per testare jump, unread e scroll progressivo."
    activity.save()
    activity.workers.set([sender_profile, recipient_profile])

    ProjectPostSeenState.objects.filter(post__project=project).delete()
    ProjectPost.objects.filter(project=project).delete()

    base_time = timezone.now() - timedelta(hours=6)
    created_posts: list[ProjectPost] = []
    for index in range(25):
        kind_cycle = [PostKind.WORK_PROGRESS, PostKind.DOCUMENTATION, PostKind.ISSUE]
        post_kind = kind_cycle[index % len(kind_cycle)]
        published_at = base_time + timedelta(minutes=index * 9)
        alert = post_kind == PostKind.ISSUE and index % 2 == 0
        author_profile = sender_profile if index % 4 else recipient_profile
        post = ProjectPost.objects.create(
            project=project,
            task=task,
            activity=activity,
            author=author_profile,
            post_kind=post_kind,
            text=f"FEED-SMOKE-{index + 1:02d} aggiornamento operativo su corridoio nord e avanzamento impianti.",
            original_text=f"FEED-SMOKE-{index + 1:02d} aggiornamento operativo su corridoio nord e avanzamento impianti.",
            source_language="it",
            display_language="it",
            alert=alert,
            is_public=False,
            published_date=published_at,
        )
        ProjectPost.objects.filter(id=post.id).update(
            created_at=published_at,
            updated_at=published_at,
        )
        post.refresh_from_db()

        if index % 5 == 0:
            comment_at = published_at + timedelta(minutes=2)
            comment = PostComment.objects.create(
                post=post,
                author=sender_profile,
                text=f"Commento smoke {index + 1:02d} con dettaglio operativo e follow-up.",
                original_text=f"Commento smoke {index + 1:02d} con dettaglio operativo e follow-up.",
                source_language="it",
                display_language="it",
            )
            PostComment.objects.filter(id=comment.id).update(
                created_at=comment_at,
                updated_at=comment_at,
            )
        created_posts.append(post)

    print(
        json.dumps(
            {
                "workspaceId": workspace.id,
                "projectId": project.id,
                "taskId": task.id,
                "activityId": activity.id,
                "postCount": len(created_posts),
                "senderEmail": SENDER_EMAIL,
                "recipientEmail": RECIPIENT_EMAIL,
                "password": DEFAULT_PASSWORD,
            }
        )
    )


if __name__ == "__main__":
    main()
