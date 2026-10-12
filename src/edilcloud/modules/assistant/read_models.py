from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from django.db.models import Case, IntegerField, Max, Value, When
from django.utils import timezone

from edilcloud.modules.assistant.query_router import AssistantQueryRoute
from edilcloud.modules.assistant.timeline_service import (
    build_project_operational_events,
    resolve_temporal_window,
)
from edilcloud.modules.projects.models import (
    PostKind,
    Project,
    ProjectActivity,
    ProjectMemberStatus,
    ProjectPost,
    ProjectTask,
    TaskActivityStatus,
)


@dataclass(slots=True)
class AssistantStructuredFacts:
    intent: str
    facts: dict[str, Any] = field(default_factory=dict)
    sections: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)


def truncate_text(value: str | None, limit: int = 180) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: max(0, limit - 3)].rstrip()}..."


def make_citation(
    *,
    index: int,
    source_key: str,
    source_type: str,
    label: str,
    snippet: str,
    metadata: dict[str, Any] | None = None,
    score: float = 1.0,
    snippet_limit: int = 240,
) -> dict[str, Any]:
    return {
        "index": index,
        "source_key": source_key,
        "source_type": source_type,
        "label": label,
        "score": round(float(score), 2),
        "snippet": truncate_text(snippet, snippet_limit),
        "metadata": metadata or {},
    }


def task_is_closed(task: ProjectTask) -> bool:
    return bool(task.date_completed) or int(task.progress or 0) >= 100


def build_project_summary_facts(project: Project, *, now: datetime | None = None) -> AssistantStructuredFacts:
    reference = timezone.localtime(now or timezone.now())
    today = reference.date()
    tasks = list(project.tasks.select_related("assigned_company").all())
    activities = list(
        ProjectActivity.objects.filter(task__project=project)
        .select_related("task", "task__assigned_company")
        .order_by("datetime_start", "id")
    )
    document_count = project.documents.count()
    team_count = project.members.filter(disabled=False, status=ProjectMemberStatus.ACTIVE).count()
    alert_query = ProjectPost.objects.filter(project=project, is_deleted=False, alert=True)
    open_alert_count = alert_query.count()
    open_alerts = list(
        alert_query.select_related("task", "activity")
        .annotate(
            issue_priority=Case(
                When(post_kind=PostKind.ISSUE, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("issue_priority", "-published_date", "-id")[:4]
    )
    post_updates = ProjectPost.objects.filter(project=project, is_deleted=False).aggregate(
        latest_published=Max("published_date"),
        latest_updated=Max("updated_at"),
    )

    open_tasks = [task for task in tasks if not task_is_closed(task)]
    overdue_tasks = sorted((task for task in open_tasks if task.date_end < today), key=lambda task: (task.date_end, task.id))
    active_activities = sorted(
        (activity for activity in activities if activity.status == TaskActivityStatus.PROGRESS),
        key=lambda activity: (activity.updated_at, activity.id),
        reverse=True,
    )
    upcoming_activities = [
        activity for activity in activities
        if activity.status == TaskActivityStatus.TODO
        and reference <= activity.datetime_start <= reference + timedelta(days=14)
    ]
    upcoming_tasks = sorted(
        (task for task in open_tasks if today < task.date_start <= today + timedelta(days=14)),
        key=lambda task: (task.date_start, task.id),
    )
    operational_updates = [
        *[task.updated_at for task in tasks],
        *[activity.updated_at for activity in activities],
    ]
    operational_updates.extend(value for value in post_updates.values() if value is not None)
    last_update = max(operational_updates) if operational_updates else None
    days_since_update = max(0, (today - timezone.localtime(last_update).date()).days) if last_update else None
    stale = days_since_update is None or days_since_update > 14

    sections = [
        f"Fotografia del progetto {project.name} al {reference.strftime('%d/%m/%Y %H:%M')}.",
        f"Ultimo aggiornamento operativo registrato: {timezone.localtime(last_update).strftime('%d/%m/%Y %H:%M') if last_update else 'non disponibile'}.",
        f"Task: {len(tasks)} totali, {len(open_tasks)} non completate, {len(overdue_tasks)} oltre la data pianificata.",
        f"Attivita marcate in corso: {len(active_activities)}. Segnalazioni marcate aperte: {open_alert_count}.",
    ]
    if stale:
        sections.append("Non ci sono aggiornamenti operativi recenti: lo stato odierno delle lavorazioni non e confermato.")
    if active_activities:
        sections.append("Attivita registrate in corso:")
        for activity in active_activities[:1]:
            sections.append(
                f"- {activity.title} (task {activity.task.name}, progresso {activity.progress}%, "
                f"fine pianificata {timezone.localtime(activity.datetime_end).strftime('%d/%m/%Y')})."
            )
    elif open_tasks:
        sections.append("Nessuna attivita e marcata in corso; le task non completate non provano lavoro in esecuzione oggi.")
    if overdue_tasks:
        sections.append("Task oltre la data pianificata:")
        for task in overdue_tasks[:1]:
            sections.append(
                f"- {task.name} (fine pianificata {task.date_end.strftime('%d/%m/%Y')}, "
                f"progresso {task.progress}%, azienda {task.assigned_company.name if task.assigned_company else 'non indicata'})."
            )
    if open_alerts:
        sections.append("Segnalazioni ancora marcate aperte:")
        for post in open_alerts[:3]:
            sections.append(
                f"- {truncate_text(post.text, 180)} "
                f"(registrata il {timezone.localtime(post.published_date).strftime('%d/%m/%Y')}, "
                f"task {post.task.name if post.task else 'non indicata'})."
            )
    if upcoming_activities or upcoming_tasks:
        sections.append("Prossime attivita pianificate nei 14 giorni:")
        for activity in upcoming_activities[:2]:
            sections.append(f"- {activity.title}: avvio {timezone.localtime(activity.datetime_start).strftime('%d/%m/%Y')}.")
        for task in upcoming_tasks[:2]:
            sections.append(f"- {task.name}: avvio {task.date_start.strftime('%d/%m/%Y')}.")
    else:
        sections.append("Nessuna nuova attivita pianificata nei prossimi 14 giorni nei dati disponibili.")
    citations = [
        make_citation(
            index=1,
            source_key=f"project:{project.id}",
            source_type="project",
            label=f"Stato operativo: {project.name}",
            snippet=(
                f"Al {reference.strftime('%d/%m/%Y')}: task non completate {len(open_tasks)}/{len(tasks)}, "
                f"oltre data {len(overdue_tasks)}, attivita marcate in corso {len(active_activities)}, "
                f"segnalazioni marcate aperte {open_alert_count}. "
                f"Ultimo aggiornamento operativo {timezone.localtime(last_update).strftime('%d/%m/%Y') if last_update else 'non disponibile'}."
            ),
            metadata={"project_id": project.id, "provenance": "structured_db", "as_of": reference.isoformat()},
        )
    ]
    for post in open_alerts[:3]:
        citations.append(
            make_citation(
                index=len(citations) + 1,
                source_key=f"post:{post.id}",
                source_type="post",
                label=truncate_text(post.text.split(".", 1)[0], 90) or f"Segnalazione #{post.id}",
                snippet=post.text,
                metadata={"project_id": project.id, "post_id": post.id, "task_id": post.task_id, "activity_id": post.activity_id, "alert": True},
                snippet_limit=600,
            )
        )
    for activity in active_activities[:1]:
        citations.append(
            make_citation(
                index=len(citations) + 1,
                source_key=f"activity:{activity.id}",
                source_type="activity",
                label=activity.title,
                snippet=f"Attivita marcata in corso: {activity.title}. Progresso {activity.progress}%.",
                metadata={"project_id": project.id, "task_id": activity.task_id, "activity_id": activity.id},
            )
        )
    for task in overdue_tasks[:1]:
        citations.append(
            make_citation(
                index=len(citations) + 1,
                source_key=f"task:{task.id}",
                source_type="task",
                label=task.name,
                snippet=f"Fine pianificata {task.date_end.isoformat()}, progresso {task.progress}%.",
                metadata={"project_id": project.id, "task_id": task.id},
            )
        )
    if upcoming_activities:
        activity = upcoming_activities[0]
        citations.append(
            make_citation(
                index=len(citations) + 1,
                source_key=f"activity:{activity.id}",
                source_type="activity",
                label=activity.title,
                snippet=f"Avvio pianificato {activity.datetime_start.isoformat()}.",
                metadata={"project_id": project.id, "task_id": activity.task_id, "activity_id": activity.id},
            )
        )

    return AssistantStructuredFacts(
        intent="project_summary",
        facts={
            "project_name": project.name,
            "as_of": reference.isoformat(),
            "last_operational_update": last_update.isoformat() if last_update else None,
            "days_since_update": days_since_update,
            "stale": stale,
            "team_count": team_count,
            "task_total_count": len(tasks),
            "task_open_count": len(open_tasks),
            "task_overdue_count": len(overdue_tasks),
            "activity_in_progress_count": len(active_activities),
            "document_count": document_count,
            "open_alert_count": open_alert_count,
            "active_activities": [activity.title for activity in active_activities[:3]],
            "overdue_tasks": [task.name for task in overdue_tasks[:3]],
            "open_alerts": [post.text for post in open_alerts[:3]],
            "upcoming_activities": [activity.title for activity in upcoming_activities[:2]],
            "upcoming_tasks": [task.name for task in upcoming_tasks[:2]],
        },
        sections=sections,
        citations=citations,
    )


def build_company_facts(project: Project, *, count_only: bool) -> AssistantStructuredFacts:
    members = list(
        project.members.select_related("profile__workspace")
        .filter(disabled=False, status=ProjectMemberStatus.ACTIVE)
        .all()
    )
    tasks = list(project.tasks.select_related("assigned_company").all())
    companies: dict[str, dict[str, Any]] = {}

    def ensure_company(name: str, *, source: str) -> None:
        normalized = (name or "").strip()
        if not normalized:
            return
        bucket = companies.setdefault(
            normalized,
            {"name": normalized, "member_count": 0, "task_count": 0, "origins": set()},
        )
        bucket["origins"].add(source)

    for member in members:
        ensure_company(member.profile.workspace.name, source="members")
        companies[member.profile.workspace.name]["member_count"] += 1
    for task in tasks:
        if task.assigned_company:
            ensure_company(task.assigned_company.name, source="tasks")
            companies[task.assigned_company.name]["task_count"] += 1

    ordered_companies = sorted(companies.values(), key=lambda item: (item["name"].lower(), -item["task_count"]))
    sections = [f"Aziende uniche rilevate: {len(ordered_companies)}"]
    for item in ordered_companies[:12]:
        origins = "/".join(sorted(item["origins"])) or "n/d"
        sections.append(
            f"- {item['name']}: membri {item['member_count']}, task {item['task_count']}, origine {origins}"
        )

    citations = [
        make_citation(
            index=1,
            source_key=f"project:{project.id}:companies",
            source_type="company_directory",
            label=f"Aziende progetto ({len(ordered_companies)})",
            snippet=" | ".join(sections[:4]),
            metadata={"company_count": len(ordered_companies)},
        )
    ]
    return AssistantStructuredFacts(
        intent="company_count" if count_only else "company_list",
        facts={"company_count": len(ordered_companies), "companies": ordered_companies[:20]},
        sections=sections if not count_only else sections[:1],
        citations=citations,
    )


def build_team_facts(project: Project, *, count_only: bool) -> AssistantStructuredFacts:
    members = list(
        project.members.select_related("profile__workspace")
        .filter(disabled=False, status=ProjectMemberStatus.ACTIVE)
        .order_by("profile__first_name", "profile__last_name", "id")
    )
    sections = [f"Totale partecipanti attivi: {len(members)}"]
    for member in members[:18]:
        sections.append(
            f"- {member.profile.member_name}: ruolo {member.get_role_display()}, azienda {member.profile.workspace.name}, esterno {'si' if member.is_external else 'no'}"
        )
    citations = [
        make_citation(
            index=1,
            source_key=f"project:{project.id}:team_directory",
            source_type="team_directory",
            label=f"Partecipanti progetto ({len(members)})",
            snippet=" | ".join(sections[:4]),
            metadata={"team_count": len(members)},
        )
    ]
    return AssistantStructuredFacts(
        intent="team_count" if count_only else "team_list",
        facts={"team_count": len(members), "members": sections[1:19]},
        sections=sections if not count_only else sections[:1],
        citations=citations,
    )


def build_task_facts(project: Project, *, intent: str) -> AssistantStructuredFacts:
    today = timezone.localdate()
    tasks = list(project.tasks.select_related("assigned_company").order_by("date_start", "id"))
    open_tasks = [task for task in tasks if not task_is_closed(task)]
    closed_tasks = [task for task in tasks if task_is_closed(task)]
    overdue_tasks = [task for task in open_tasks if task.date_end < today]
    alert_tasks = [task for task in tasks if task.alert]

    sections = [
        f"Task totali: {len(tasks)}",
        f"Task aperte: {len(open_tasks)}",
        f"Task chiuse: {len(closed_tasks)}",
        f"Task in ritardo: {len(overdue_tasks)}",
        f"Task con alert: {len(alert_tasks)}",
    ]
    details = [
        f"- {task.name}: azienda {task.assigned_company.name if task.assigned_company else 'N/D'}, progresso {task.progress}%, alert {'si' if task.alert else 'no'}"
        for task in tasks[:16]
    ]
    citations = [
        make_citation(
            index=1,
            source_key=f"project:{project.id}:task_summary",
            source_type="task_summary",
            label=f"Task progetto ({len(tasks)})",
            snippet=" | ".join(sections),
            metadata={
                "task_total_count": len(tasks),
                "task_open_count": len(open_tasks),
                "task_closed_count": len(closed_tasks),
            },
        )
    ]
    for offset, task in enumerate(tasks[:3], start=2):
        citations.append(
            make_citation(
                index=offset,
                source_key=f"task:{task.id}",
                source_type="task",
                label=task.name,
                snippet=details[offset - 2],
                metadata={"task_id": task.id},
            )
        )
    return AssistantStructuredFacts(
        intent=intent,
        facts={
            "task_total_count": len(tasks),
            "task_open_count": len(open_tasks),
            "task_closed_count": len(closed_tasks),
            "task_overdue_count": len(overdue_tasks),
            "task_alert_count": len(alert_tasks),
            "tasks": details,
        },
        sections=sections + ([] if intent == "task_count" else details),
        citations=citations,
    )


def build_alert_facts(project: Project, *, resolved: bool) -> AssistantStructuredFacts:
    queryset = ProjectPost.objects.filter(project=project, is_deleted=False)
    if resolved:
        queryset = queryset.filter(post_kind=PostKind.ISSUE, alert=False)
        title = "Segnalazioni risolte"
        source_key = f"project:{project.id}:resolved_issues"
        source_type = "resolved_issues_summary"
        intent = "resolved_issues"
    else:
        queryset = queryset.filter(alert=True)
        title = "Segnalazioni aperte"
        source_key = f"project:{project.id}:open_alerts"
        source_type = "open_alerts_summary"
        intent = "open_alerts"

    count = queryset.count()
    posts = list(queryset.select_related("task__assigned_company", "activity", "author").order_by("-published_date", "-id")[:18])
    sections = [f"{title}: {count}"]
    citations = [
        make_citation(
            index=1,
            source_key=source_key,
            source_type=source_type,
            label=f"{title} ({count})",
            snippet=f"{title}: {count}",
            metadata={"issue_status": "resolved" if resolved else "open"},
        )
    ]
    for offset, post in enumerate(posts[:8], start=2):
        company = post.task.assigned_company.name if post.task and post.task.assigned_company else "non assegnata"
        snippet = (
            f"- {post.task.name if post.task else 'N/D'} / {post.activity.title if post.activity else 'N/D'}: "
            f"Azienda assegnata alla fase: {company}; autore della segnalazione: {post.author.member_name}; "
            f"data: {post.published_date.date().isoformat()}. {truncate_text(post.text, 360)}"
        )
        sections.append(snippet)
        citations.append(
            make_citation(
                index=offset,
                source_key=f"post:{post.id}",
                source_type="post",
                label=post.activity.title if post.activity else post.task.name if post.task else title,
                snippet=snippet,
                metadata={"post_id": post.id, "task_id": post.task_id, "activity_id": post.activity_id, "assigned_company": company, "author_name": post.author.member_name},
            )
        )

    return AssistantStructuredFacts(
        intent=intent,
        facts={"count": count, "items": sections[1:]},
        sections=sections,
        citations=citations,
    )


def build_document_facts(project: Project, *, search_like: bool) -> AssistantStructuredFacts:
    documents = list(project.documents.select_related("folder").order_by("-updated_at", "-id"))
    sections = [f"Documenti totali: {len(documents)}"]
    extracted_count = 0
    for document in documents[:18]:
        extension = Path(getattr(document.document, "name", "")).suffix.lower()
        if extension in {".pdf", ".rtf", ".txt", ".md", ".html", ".xml"}:
            extracted_count += 1
        sections.append(
            f"- {document.title}: cartella {document.folder.name if document.folder else 'N/D'}, file {Path(getattr(document.document, 'name', '')).name or 'N/D'}"
        )
    citations = [
        make_citation(
            index=1,
            source_key=f"project:{project.id}:documents_catalog",
            source_type="documents_catalog",
            label=f"Registro documenti ({len(documents)})",
            snippet=" | ".join(sections[:4]),
            metadata={"document_count": len(documents), "extractable_count": extracted_count},
        )
    ]
    return AssistantStructuredFacts(
        intent="document_search" if search_like else "document_list",
        facts={"document_count": len(documents), "extractable_count": extracted_count, "documents": sections[1:]},
        sections=sections,
        citations=citations,
    )


def build_timeline_facts(project: Project, question: str, *, intent: str) -> AssistantStructuredFacts:
    start_at, end_at, window_label = resolve_temporal_window(question)
    events = build_project_operational_events(project=project, start_at=start_at, end_at=end_at, limit=20)
    sections = [f"Finestra temporale: {window_label}", f"Eventi trovati: {len(events)}"]
    citations: list[dict[str, Any]] = []
    for offset, event in enumerate(events[:10], start=1):
        line = f"- {timezone.localtime(event.event_at).strftime('%d/%m %H:%M')}: {event.summary}"
        sections.append(line)
        citations.append(
            make_citation(
                index=offset,
                source_key=f"{event.source_type}:{offset}",
                source_type=event.source_type,
                label=event.label,
                snippet=line,
                metadata={
                    "task_id": event.task_id,
                    "activity_id": event.activity_id,
                    "event_at": event.event_at.isoformat(),
                },
            )
        )
    return AssistantStructuredFacts(
        intent=intent,
        facts={"window_label": window_label, "event_count": len(events), "events": sections[2:]},
        sections=sections,
        citations=citations,
    )


def build_structured_facts(
    *,
    project: Project,
    route: AssistantQueryRoute,
    question: str,
) -> AssistantStructuredFacts:
    if route.intent == "project_summary":
        return build_project_summary_facts(project)
    if route.intent == "company_count":
        return build_company_facts(project, count_only=True)
    if route.intent == "company_list":
        return build_company_facts(project, count_only=False)
    if route.intent == "team_count":
        return build_team_facts(project, count_only=True)
    if route.intent == "team_list":
        return build_team_facts(project, count_only=False)
    if route.intent in {"task_count", "task_list", "task_status"}:
        return build_task_facts(project, intent=route.intent)
    if route.intent == "activity_by_date":
        return build_timeline_facts(project, question, intent=route.intent)
    if route.intent == "timeline_summary":
        return build_timeline_facts(project, question, intent=route.intent)
    if route.intent == "open_alerts":
        return build_alert_facts(project, resolved=False)
    if route.intent == "resolved_issues":
        return build_alert_facts(project, resolved=True)
    if route.intent == "document_list":
        return build_document_facts(project, search_like=False)
    if route.intent == "document_search":
        return build_document_facts(project, search_like=True)
    return AssistantStructuredFacts(intent=route.intent, facts={}, sections=[], citations=[])
