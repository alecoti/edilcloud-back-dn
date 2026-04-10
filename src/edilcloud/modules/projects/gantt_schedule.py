"""Scheduling helpers for project Gantt links, delays, and phase guard rails."""

from __future__ import annotations

from collections import deque
from datetime import date, timedelta

from django.db.models import Max, Min
from django.utils import timezone

from edilcloud.modules.projects.models import (
    Project,
    ProjectActivity,
    ProjectScheduleLink,
    ProjectScheduleLinkType,
    ProjectTask,
)


MAX_PROPAGATION_STEPS = 4096


def schedule_link_entity_ref(*, task: ProjectTask | None = None, activity: ProjectActivity | None = None) -> str | None:
    if activity is not None:
        return f"activity-{activity.id}"
    if task is not None:
        return f"task-{task.id}"
    return None


def normalize_schedule_link_type(value: str | None) -> str:
    return value if value in ProjectScheduleLinkType.values else ProjectScheduleLinkType.END_TO_START


def normalize_schedule_link_lag_days(value: int | None) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_schedule_entity_ref(entity_ref: str) -> tuple[str, int]:
    normalized = (entity_ref or "").strip().lower()
    prefix, separator, raw_id = normalized.partition("-")
    if separator != "-" or prefix not in {"task", "activity"} or not raw_id.isdigit():
        raise ValueError("Vincolo Gantt non valido.")
    return prefix, int(raw_id)


def resolve_project_schedule_entity(*, project: Project, entity_ref: str) -> ProjectTask | ProjectActivity | None:
    kind, entity_id = parse_schedule_entity_ref(entity_ref)
    if kind == "task":
        return ProjectTask.objects.filter(project=project, id=entity_id).first()
    return (
        ProjectActivity.objects.select_related("task")
        .filter(id=entity_id, task__project=project)
        .first()
    )


def resolve_project_schedule_endpoints(
    *,
    project: Project,
    source_ref: str,
    target_ref: str,
) -> tuple[ProjectTask | None, ProjectActivity | None, ProjectTask | None, ProjectActivity | None]:
    source = resolve_project_schedule_entity(project=project, entity_ref=source_ref)
    target = resolve_project_schedule_entity(project=project, entity_ref=target_ref)
    if source is None or target is None:
        raise ValueError("Uno dei riferimenti Gantt non esiste in questo progetto.")

    source_task = source if isinstance(source, ProjectTask) else None
    source_activity = source if isinstance(source, ProjectActivity) else None
    target_task = target if isinstance(target, ProjectTask) else None
    target_activity = target if isinstance(target, ProjectActivity) else None

    if source_task is not None and target_task is not None and source_task.id == target_task.id:
        raise ValueError("Non puoi collegare una fase a se stessa.")
    if source_activity is not None and target_activity is not None and source_activity.id == target_activity.id:
        raise ValueError("Non puoi collegare un'attivita a se stessa.")
    if source_task is not None and target_activity is not None and target_activity.task_id == source_task.id:
        raise ValueError("Non puoi collegare una fase a una sua attivita.")
    if source_activity is not None and target_task is not None and source_activity.task_id == target_task.id:
        raise ValueError("Non puoi collegare un'attivita alla fase che la contiene.")

    return source_task, source_activity, target_task, target_activity


def project_schedule_would_create_cycle(
    *,
    project: Project,
    source_ref: str,
    target_ref: str,
    exclude_link_id: int | None = None,
) -> bool:
    if source_ref == target_ref:
        return True

    adjacency: dict[str, list[str]] = {}
    links = ProjectScheduleLink.objects.select_related(
        "source_task",
        "source_activity",
        "target_task",
        "target_activity",
    ).filter(project=project)
    if exclude_link_id is not None:
        links = links.exclude(id=exclude_link_id)

    for link in links:
        existing_source = schedule_link_entity_ref(task=link.source_task, activity=link.source_activity)
        existing_target = schedule_link_entity_ref(task=link.target_task, activity=link.target_activity)
        if not existing_source or not existing_target:
            continue
        adjacency.setdefault(existing_source, []).append(existing_target)

    queue = deque([target_ref])
    seen = {target_ref}
    while queue:
        current = queue.popleft()
        if current == source_ref:
            return True
        for next_ref in adjacency.get(current, []):
            if next_ref in seen:
                continue
            seen.add(next_ref)
            queue.append(next_ref)
    return False


def create_project_schedule_link_record(
    *,
    project: Project,
    source_ref: str,
    target_ref: str,
    link_type: str | None = None,
    lag_days: int | None = None,
    origin: str = "manual",
    apply_constraints: bool = True,
) -> ProjectScheduleLink:
    source_task, source_activity, target_task, target_activity = resolve_project_schedule_endpoints(
        project=project,
        source_ref=source_ref,
        target_ref=target_ref,
    )
    if ProjectScheduleLink.objects.filter(
        project=project,
        source_task=source_task,
        source_activity=source_activity,
        target_task=target_task,
        target_activity=target_activity,
    ).exists():
        raise ValueError("Questo vincolo esiste gia nel Gantt.")
    if project_schedule_would_create_cycle(project=project, source_ref=source_ref, target_ref=target_ref):
        raise ValueError("Questo vincolo creerebbe un ciclo nel cronoprogramma.")

    link = ProjectScheduleLink.objects.create(
        project=project,
        source_task=source_task,
        source_activity=source_activity,
        target_task=target_task,
        target_activity=target_activity,
        link_type=normalize_schedule_link_type(link_type),
        lag_days=normalize_schedule_link_lag_days(lag_days),
        origin=(origin or "manual").strip() or "manual",
    )
    if apply_constraints:
        propagate_project_schedule_delays(project=project, seed_refs=[source_ref])
    return link


def update_project_schedule_link_record(
    *,
    link: ProjectScheduleLink,
    source_ref: str | None = None,
    target_ref: str | None = None,
    link_type: str | None = None,
    lag_days: int | None = None,
    apply_constraints: bool = True,
) -> ProjectScheduleLink:
    next_source_ref = source_ref or schedule_link_entity_ref(task=link.source_task, activity=link.source_activity)
    next_target_ref = target_ref or schedule_link_entity_ref(task=link.target_task, activity=link.target_activity)
    if not next_source_ref or not next_target_ref:
        raise ValueError("Il vincolo Gantt non e piu valido.")

    source_task, source_activity, target_task, target_activity = resolve_project_schedule_endpoints(
        project=link.project,
        source_ref=next_source_ref,
        target_ref=next_target_ref,
    )
    duplicate_qs = ProjectScheduleLink.objects.filter(
        project=link.project,
        source_task=source_task,
        source_activity=source_activity,
        target_task=target_task,
        target_activity=target_activity,
    ).exclude(id=link.id)
    if duplicate_qs.exists():
        raise ValueError("Esiste gia un vincolo uguale nel Gantt.")
    if project_schedule_would_create_cycle(
        project=link.project,
        source_ref=next_source_ref,
        target_ref=next_target_ref,
        exclude_link_id=link.id,
    ):
        raise ValueError("Questo vincolo creerebbe un ciclo nel cronoprogramma.")

    link.source_task = source_task
    link.source_activity = source_activity
    link.target_task = target_task
    link.target_activity = target_activity
    link.link_type = normalize_schedule_link_type(link_type or link.link_type)
    if lag_days is not None:
        link.lag_days = normalize_schedule_link_lag_days(lag_days)
    link.save()
    if apply_constraints:
        propagate_project_schedule_delays(project=link.project, seed_refs=[next_source_ref])
    return link


def delete_project_schedule_link_record(*, link: ProjectScheduleLink) -> None:
    link.delete()


def shift_task_activities_only(*, task_id: int, delta_days: int) -> list[str]:
    return _shift_task_bundle(task_id=task_id, delta_days=delta_days, shift_task=False)


def sync_task_bounds_to_activities(*, task_id: int) -> str | None:
    aggregate = ProjectActivity.objects.filter(task_id=task_id).aggregate(
        min_start=Min("datetime_start"),
        max_end=Max("datetime_end"),
    )
    min_start = aggregate.get("min_start")
    max_end = aggregate.get("max_end")
    if min_start is None or max_end is None:
        return None

    task = ProjectTask.objects.filter(id=task_id).first()
    if task is None:
        return None

    next_start = min(task.date_start, _schedule_date_for_datetime(min_start))
    next_end = max(task.date_end, _schedule_date_for_datetime(max_end))
    if next_start == task.date_start and next_end == task.date_end:
        return None

    task.date_start = next_start
    task.date_end = next_end
    task.save(update_fields=("date_start", "date_end", "updated_at"))
    return schedule_link_entity_ref(task=task)


def propagate_project_schedule_delays(*, project: Project, seed_refs: list[str] | tuple[str, ...]) -> list[str]:
    queue = deque[str]()
    queued: set[str] = set()
    affected_refs: list[str] = []
    affected_seen: set[str] = set()

    for raw_ref in seed_refs:
        normalized_ref = (raw_ref or "").strip().lower()
        if not normalized_ref or normalized_ref in queued:
            continue
        queue.append(normalized_ref)
        queued.add(normalized_ref)

    steps = 0
    while queue:
        current_ref = queue.popleft()
        queued.discard(current_ref)
        steps += 1
        if steps > MAX_PROPAGATION_STEPS:
            raise ValueError("Il Gantt contiene troppi ricalcoli concatenati.")

        source = resolve_project_schedule_entity(project=project, entity_ref=current_ref)
        if source is None:
            continue

        kind, entity_id = parse_schedule_entity_ref(current_ref)
        link_filter = {"source_task_id": entity_id} if kind == "task" else {"source_activity_id": entity_id}
        outgoing_links = ProjectScheduleLink.objects.select_related(
            "target_task",
            "target_activity",
            "target_activity__task",
        ).filter(project=project, **link_filter)

        for link in outgoing_links:
            target = link.target_activity or link.target_task
            if target is None:
                continue
            delta_days = _required_delay_days(
                source=source,
                target=target,
                link_type=link.link_type,
                lag_days=link.lag_days,
            )
            if delta_days <= 0:
                continue

            if link.target_task_id:
                moved_refs = _shift_task_bundle(
                    task_id=link.target_task_id,
                    delta_days=delta_days,
                    shift_task=True,
                )
            else:
                moved_refs = _shift_activity(activity_id=link.target_activity_id, delta_days=delta_days)
                parent_task_ref = (
                    sync_task_bounds_to_activities(task_id=link.target_activity.task_id)
                    if link.target_activity_id and link.target_activity is not None
                    else None
                )
                if parent_task_ref:
                    moved_refs.append(parent_task_ref)

            for moved_ref in moved_refs:
                if not moved_ref:
                    continue
                if moved_ref not in affected_seen:
                    affected_seen.add(moved_ref)
                    affected_refs.append(moved_ref)
                if moved_ref not in queued:
                    queue.append(moved_ref)
                    queued.add(moved_ref)

    return affected_refs


def _shift_task_bundle(*, task_id: int, delta_days: int, shift_task: bool) -> list[str]:
    if delta_days == 0:
        return []

    task = ProjectTask.objects.prefetch_related("activities").filter(id=task_id).first()
    if task is None:
        return []

    moved_refs: list[str] = []
    if shift_task:
        task.date_start = task.date_start + timedelta(days=delta_days)
        task.date_end = task.date_end + timedelta(days=delta_days)
        task.save(update_fields=("date_start", "date_end", "updated_at"))
        task_ref = schedule_link_entity_ref(task=task)
        if task_ref:
            moved_refs.append(task_ref)

    for activity in task.activities.all():
        activity.datetime_start = activity.datetime_start + timedelta(days=delta_days)
        activity.datetime_end = activity.datetime_end + timedelta(days=delta_days)
        activity.save(update_fields=("datetime_start", "datetime_end", "updated_at"))
        activity_ref = schedule_link_entity_ref(activity=activity)
        if activity_ref:
            moved_refs.append(activity_ref)

    return moved_refs


def _shift_activity(*, activity_id: int | None, delta_days: int) -> list[str]:
    if not activity_id or delta_days == 0:
        return []

    activity = ProjectActivity.objects.select_related("task").filter(id=activity_id).first()
    if activity is None:
        return []

    activity.datetime_start = activity.datetime_start + timedelta(days=delta_days)
    activity.datetime_end = activity.datetime_end + timedelta(days=delta_days)
    activity.save(update_fields=("datetime_start", "datetime_end", "updated_at"))
    activity_ref = schedule_link_entity_ref(activity=activity)
    return [activity_ref] if activity_ref else []


def _entity_date_start(entity: ProjectTask | ProjectActivity) -> date:
    if isinstance(entity, ProjectTask):
        return entity.date_start
    return _schedule_date_for_datetime(entity.datetime_start)


def _entity_date_end(entity: ProjectTask | ProjectActivity) -> date:
    if isinstance(entity, ProjectTask):
        return entity.date_end
    return _schedule_date_for_datetime(entity.datetime_end)


def _schedule_date_for_datetime(value) -> date:
    if timezone.is_aware(value):
        return timezone.localtime(value).date()
    return value.date()


def _required_delay_days(
    *,
    source: ProjectTask | ProjectActivity,
    target: ProjectTask | ProjectActivity,
    link_type: str,
    lag_days: int,
) -> int:
    normalized_type = normalize_schedule_link_type(link_type)
    normalized_lag = normalize_schedule_link_lag_days(lag_days)

    source_start = _entity_date_start(source)
    source_end = _entity_date_end(source)
    target_start = _entity_date_start(target)
    target_end = _entity_date_end(target)

    if normalized_type == ProjectScheduleLinkType.START_TO_START:
        required_start = source_start + timedelta(days=normalized_lag)
        return max(0, (required_start - target_start).days)
    if normalized_type == ProjectScheduleLinkType.END_TO_END:
        required_end = source_end + timedelta(days=normalized_lag)
        return max(0, (required_end - target_end).days)
    if normalized_type == ProjectScheduleLinkType.START_TO_END:
        required_end = source_start + timedelta(days=normalized_lag)
        return max(0, (required_end - target_end).days)

    required_start = source_end + timedelta(days=normalized_lag + 1)
    return max(0, (required_start - target_start).days)
