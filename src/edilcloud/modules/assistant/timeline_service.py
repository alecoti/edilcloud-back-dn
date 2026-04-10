from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from edilcloud.modules.projects.models import (
    PostComment,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectPhoto,
    ProjectPost,
    ProjectTask,
    TaskActivityStatus,
)


@dataclass(slots=True)
class ProjectOperationalEvent:
    source_type: str
    label: str
    event_at: datetime
    summary: str
    task_id: int | None = None
    activity_id: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


def combine_date_range(day_start: date, day_end: date) -> tuple[datetime, datetime]:
    current_tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(day_start, time.min), current_tz),
        timezone.make_aware(datetime.combine(day_end, time.max), current_tz),
    )


def resolve_temporal_window(question: str, *, now: datetime | None = None) -> tuple[datetime, datetime, str]:
    reference = now or timezone.now()
    lowered = (question or "").strip().lower()
    today = reference.date()

    if "ieri" in lowered:
        start, end = combine_date_range(today - timedelta(days=1), today - timedelta(days=1))
        return start, end, "ieri"
    if "oggi" in lowered:
        start, end = combine_date_range(today, today)
        return start, end, "oggi"
    if "settimana scorsa" in lowered:
        this_week_start = today - timedelta(days=today.weekday())
        previous_week_start = this_week_start - timedelta(days=7)
        previous_week_end = previous_week_start + timedelta(days=6)
        start, end = combine_date_range(previous_week_start, previous_week_end)
        return start, end, "settimana_scorsa"
    if "ultimi 7 giorni" in lowered:
        start, end = combine_date_range(today - timedelta(days=6), today)
        return start, end, "ultimi_7_giorni"
    start, end = combine_date_range(today - timedelta(days=13), today)
    return start, end, "ultimi_14_giorni"


def build_project_operational_events(
    *,
    project: Project,
    start_at: datetime,
    end_at: datetime,
    limit: int = 32,
) -> list[ProjectOperationalEvent]:
    events: list[ProjectOperationalEvent] = []

    created_tasks = (
        ProjectTask.objects.filter(project=project, created_at__range=(start_at, end_at))
        .select_related("assigned_company")
        .order_by("-created_at", "-id")
    )
    for task in created_tasks:
        events.append(
            ProjectOperationalEvent(
                source_type="task_created",
                label=task.name,
                event_at=task.created_at,
                summary=f"Task creata: {task.name}",
                task_id=task.id,
                metadata={"assigned_company": task.assigned_company.name if task.assigned_company else None},
            )
        )

    completed_tasks = (
        ProjectTask.objects.filter(project=project, date_completed__isnull=False)
        .select_related("assigned_company")
        .order_by("-date_completed", "-id")
    )
    for task in completed_tasks:
        completion_at = timezone.make_aware(datetime.combine(task.date_completed, time(hour=12)))
        if completion_at < start_at or completion_at > end_at:
            continue
        events.append(
            ProjectOperationalEvent(
                source_type="task_completed",
                label=task.name,
                event_at=completion_at,
                summary=f"Task completata: {task.name}",
                task_id=task.id,
                metadata={"assigned_company": task.assigned_company.name if task.assigned_company else None},
            )
        )

    activities = (
        ProjectActivity.objects.filter(task__project=project, datetime_start__lte=end_at, datetime_end__gte=start_at)
        .select_related("task")
        .order_by("-datetime_start", "-id")
    )
    for activity in activities:
        events.append(
            ProjectOperationalEvent(
                source_type="activity_window",
                label=activity.title,
                event_at=activity.datetime_start,
                summary=f"Attivita {activity.get_status_display().lower()}: {activity.title}",
                task_id=activity.task_id,
                activity_id=activity.id,
                metadata={"status": activity.status},
            )
        )
        if activity.status == TaskActivityStatus.COMPLETED:
            events.append(
                ProjectOperationalEvent(
                    source_type="activity_completed",
                    label=activity.title,
                    event_at=activity.datetime_end,
                    summary=f"Attivita conclusa: {activity.title}",
                    task_id=activity.task_id,
                    activity_id=activity.id,
                    metadata={"status": activity.status},
                )
            )

    posts = (
        ProjectPost.objects.filter(project=project, is_deleted=False, published_date__range=(start_at, end_at))
        .select_related("task", "activity", "author")
        .order_by("-published_date", "-id")
    )
    for post in posts:
        events.append(
            ProjectOperationalEvent(
                source_type="post",
                label=f"Post #{post.id}",
                event_at=post.published_date,
                summary=f"Post {post.get_post_kind_display().lower()}: {(post.text or '').strip()[:140]}",
                task_id=post.task_id,
                activity_id=post.activity_id,
                metadata={"alert": post.alert, "post_kind": post.post_kind},
            )
        )

    comments = (
        PostComment.objects.filter(post__project=project, is_deleted=False, created_at__range=(start_at, end_at))
        .select_related("post")
        .order_by("-created_at", "-id")
    )
    for comment in comments:
        events.append(
            ProjectOperationalEvent(
                source_type="comment",
                label=f"Comment #{comment.id}",
                event_at=comment.created_at,
                summary=f"Commento inserito: {(comment.text or '').strip()[:140]}",
                task_id=comment.post.task_id,
                activity_id=comment.post.activity_id,
                metadata={"post_id": comment.post_id},
            )
        )

    documents = (
        ProjectDocument.objects.filter(project=project, updated_at__range=(start_at, end_at))
        .select_related("folder")
        .order_by("-updated_at", "-id")
    )
    for document in documents:
        events.append(
            ProjectOperationalEvent(
                source_type="document",
                label=document.title,
                event_at=document.updated_at,
                summary=f"Documento aggiornato o caricato: {document.title}",
                metadata={"document_id": document.id, "folder_id": document.folder_id},
            )
        )

    photos = ProjectPhoto.objects.filter(project=project, created_at__range=(start_at, end_at)).order_by(
        "-created_at",
        "-id",
    )
    for photo in photos:
        events.append(
            ProjectOperationalEvent(
                source_type="photo",
                label=photo.title or f"Foto {photo.id}",
                event_at=photo.created_at,
                summary=f"Foto caricata: {photo.title or f'Foto {photo.id}'}",
                metadata={"photo_id": photo.id},
            )
        )

    ordered_events = sorted(events, key=lambda item: item.event_at, reverse=True)
    return ordered_events[:limit]
