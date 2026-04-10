from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.utils import timezone

from edilcloud.modules.assistant.query_router import AssistantQueryRoute
from edilcloud.modules.assistant.timeline_service import (
    build_project_operational_events,
    resolve_temporal_window,
)
from edilcloud.modules.projects.models import PostKind, Project, ProjectMemberStatus, ProjectPost, ProjectTask


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
) -> dict[str, Any]:
    return {
        "index": index,
        "source_key": source_key,
        "source_type": source_type,
        "label": label,
        "score": round(float(score), 2),
        "snippet": truncate_text(snippet, 240),
        "metadata": metadata or {},
    }


def task_is_closed(task: ProjectTask) -> bool:
    return bool(task.date_completed) or int(task.progress or 0) >= 100


def build_project_summary_facts(project: Project) -> AssistantStructuredFacts:
    today = timezone.localdate()
    tasks = list(project.tasks.select_related("assigned_company").all())
    documents = list(project.documents.select_related("folder").all())
    members = list(
        project.members.select_related("profile__workspace")
        .filter(disabled=False, status=ProjectMemberStatus.ACTIVE)
        .all()
    )
    open_alerts = list(ProjectPost.objects.filter(project=project, is_deleted=False, alert=True).order_by("-published_date")[:5])
    recent_events = build_project_operational_events(
        project=project,
        start_at=timezone.now() - timedelta(days=7),
        end_at=timezone.now(),
        limit=6,
    )
    open_tasks = [task for task in tasks if not task_is_closed(task)]
    overdue_tasks = [task for task in open_tasks if task.date_end < today]

    citations = [
        make_citation(
            index=1,
            source_key=f"project:{project.id}",
            source_type="project",
            label=project.name,
            snippet=f"Task aperte: {len(open_tasks)}. Documenti: {len(documents)}. Alert aperti: {len(open_alerts)}.",
            metadata={"project_id": project.id},
        )
    ]
    for offset, event in enumerate(recent_events[:3], start=2):
        citations.append(
            make_citation(
                index=offset,
                source_key=f"{event.source_type}:{offset}",
                source_type=event.source_type,
                label=event.label,
                snippet=event.summary,
                metadata={
                    "task_id": event.task_id,
                    "activity_id": event.activity_id,
                    "event_at": event.event_at.isoformat(),
                },
            )
        )

    return AssistantStructuredFacts(
        intent="project_summary",
        facts={
            "project_name": project.name,
            "team_count": len(members),
            "task_open_count": len(open_tasks),
            "task_overdue_count": len(overdue_tasks),
            "document_count": len(documents),
            "open_alert_count": len(open_alerts),
            "recent_events": [event.summary for event in recent_events[:6]],
        },
        sections=[
            f"Progetto: {project.name}",
            f"Partecipanti attivi: {len(members)}",
            f"Task aperte: {len(open_tasks)}",
            f"Task in ritardo: {len(overdue_tasks)}",
            f"Documenti: {len(documents)}",
            f"Alert aperti: {len(open_alerts)}",
        ],
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
        posts = list(queryset.filter(post_kind=PostKind.ISSUE, alert=False).select_related("task", "activity").order_by("-published_date")[:18])
        title = "Segnalazioni risolte"
        source_key = f"project:{project.id}:resolved_issues"
        source_type = "resolved_issues_summary"
        intent = "resolved_issues"
    else:
        posts = list(queryset.filter(alert=True).select_related("task", "activity").order_by("-published_date")[:18])
        title = "Segnalazioni aperte"
        source_key = f"project:{project.id}:open_alerts"
        source_type = "open_alerts_summary"
        intent = "open_alerts"

    sections = [f"{title}: {len(posts)}"]
    citations = [
        make_citation(
            index=1,
            source_key=source_key,
            source_type=source_type,
            label=f"{title} ({len(posts)})",
            snippet=f"{title}: {len(posts)}",
            metadata={"issue_status": "resolved" if resolved else "open"},
        )
    ]
    for offset, post in enumerate(posts[:8], start=2):
        snippet = (
            f"- {post.task.name if post.task else 'N/D'} / {post.activity.title if post.activity else 'N/D'}: "
            f"{truncate_text(post.text, 180)}"
        )
        sections.append(snippet)
        citations.append(
            make_citation(
                index=offset,
                source_key=f"post:{post.id}",
                source_type="post",
                label=f"{title[:-1]} #{post.id}",
                snippet=snippet,
                metadata={"post_id": post.id, "task_id": post.task_id, "activity_id": post.activity_id},
            )
        )

    return AssistantStructuredFacts(
        intent=intent,
        facts={"count": len(posts), "items": sections[1:]},
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
