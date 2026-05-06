from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from edilcloud.modules.assistant.models import AssistantWikiPageType, ProjectAssistantWikiPage
from edilcloud.modules.projects.models import (
    PostKind,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectMember,
    ProjectPost,
    ProjectTask,
    TaskActivityStatus,
)


PROJECT_WIKI_SCHEMA_VERSION = "project-wiki:v1"
DECISION_MARKERS = ("approvat", "validat", "decis", "confermat", "chius", "autorizzat")


@dataclass(slots=True)
class WikiPageDraft:
    slug: str
    page_type: str
    title: str
    body_markdown: str
    summary: str
    source_refs: list[dict[str, Any]]
    metadata: dict[str, Any]


@dataclass(slots=True)
class ProjectWikiContext:
    project: Project
    tasks: list[ProjectTask]
    activities: list[ProjectActivity]
    posts: list[ProjectPost]
    documents: list[ProjectDocument]
    members: list[ProjectMember]


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def compact_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", normalize_text(value))


def truncate_text(value: str, limit: int = 240) -> str:
    cleaned = compact_whitespace(value)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: max(0, limit - 3)].rstrip()}..."


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def format_date(value: Any) -> str:
    if value is None:
        return "N/A"
    if hasattr(value, "date") and not isinstance(value, str):
        try:
            return str(value.date())
        except Exception:
            return str(value)
    return str(value)


def wiki_source_ref(
    source_type: str,
    source_key: str,
    label: str,
    **metadata: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_type": source_type,
        "source_key": source_key,
        "label": truncate_text(label, 160),
    }
    clean_metadata = {
        key: value
        for key, value in metadata.items()
        if value not in (None, "") and not (isinstance(value, list) and not value)
    }
    if clean_metadata:
        payload["metadata"] = clean_metadata
    return payload


def source_ref_key(source_ref: dict[str, Any]) -> str:
    return str(source_ref.get("source_key") or "")


def dedupe_source_refs(source_refs: list[dict[str, Any]], limit: int = 80) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for source_ref in source_refs:
        key = source_ref_key(source_ref)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(source_ref)
        if len(deduped) >= limit:
            break
    return deduped


def markdown_list(items: list[str], empty: str) -> list[str]:
    return [f"- {item}" for item in items] if items else [f"- {empty}"]


def collect_project_wiki_context(project: Project) -> ProjectWikiContext:
    tasks = list(
        project.tasks.select_related("assigned_company")
        .prefetch_related("activities__workers")
        .order_by("date_start", "id")
    )
    activities = list(
        ProjectActivity.objects.filter(task__project=project)
        .select_related("task")
        .prefetch_related("workers")
        .order_by("datetime_start", "id")
    )
    posts = list(
        ProjectPost.objects.filter(project=project, is_deleted=False)
        .select_related("author__workspace", "author__user", "task", "activity")
        .order_by("-published_date", "-id")
    )
    documents = list(project.documents.select_related("folder").order_by("-updated_at", "-id"))
    members = list(
        project.members.select_related("profile__workspace", "profile__user")
        .filter(disabled=False)
        .order_by("profile__workspace__name", "profile__first_name", "profile__last_name", "id")
    )
    return ProjectWikiContext(
        project=project,
        tasks=tasks,
        activities=activities,
        posts=posts,
        documents=documents,
        members=members,
    )


def project_wiki_version(context: ProjectWikiContext) -> int:
    timestamps: list[datetime] = [context.project.updated_at]
    timestamps.extend(task.updated_at for task in context.tasks)
    timestamps.extend(activity.updated_at for activity in context.activities)
    timestamps.extend(post.updated_at for post in context.posts)
    timestamps.extend(document.updated_at for document in context.documents)
    timestamps.extend(member.updated_at for member in context.members)
    latest = max(timestamps, default=timezone.now())
    return int(latest.timestamp() * 1000)


def task_source_ref(task: ProjectTask) -> dict[str, Any]:
    return wiki_source_ref(
        "task",
        f"task:{task.id}",
        task.name,
        task_id=task.id,
        progress=task.progress,
        alert=task.alert,
        company_name=task.assigned_company.name if task.assigned_company else None,
    )


def activity_source_ref(activity: ProjectActivity) -> dict[str, Any]:
    return wiki_source_ref(
        "activity",
        f"activity:{activity.id}",
        activity.title,
        activity_id=activity.id,
        task_id=activity.task_id,
        status=activity.status,
        alert=activity.alert,
    )


def post_source_ref(post: ProjectPost) -> dict[str, Any]:
    return wiki_source_ref(
        "post",
        f"post:{post.id}",
        truncate_text(post.text or f"Post {post.id}", 120),
        post_id=post.id,
        task_id=post.task_id,
        activity_id=post.activity_id,
        post_kind=post.post_kind,
        alert=post.alert,
        event_at=post.published_date.isoformat() if post.published_date else None,
    )


def document_source_ref(document: ProjectDocument) -> dict[str, Any]:
    return wiki_source_ref(
        "document",
        f"document:{document.id}",
        document.title or f"Documento {document.id}",
        document_id=document.id,
        folder_name=document.folder.name if document.folder else None,
        is_public=document.is_public,
        document_kind=document.document_kind,
    )


def member_source_ref(member: ProjectMember) -> dict[str, Any]:
    return wiki_source_ref(
        "team_member",
        f"member:{member.id}",
        member.profile.member_name,
        member_id=member.id,
        profile_id=member.profile_id,
        workspace_name=member.profile.workspace.name,
        role=member.get_role_display(),
        is_external=member.is_external,
    )


def project_source_ref(project: Project) -> dict[str, Any]:
    return wiki_source_ref(
        "project",
        f"project:{project.id}",
        project.name,
        project_id=project.id,
        workspace_name=project.workspace.name,
    )


def average_task_progress(tasks: list[ProjectTask]) -> int:
    if not tasks:
        return 0
    return round(sum(int(task.progress or 0) for task in tasks) / len(tasks))


def company_names(context: ProjectWikiContext) -> list[str]:
    names = {
        member.profile.workspace.name
        for member in context.members
        if normalize_text(member.profile.workspace.name)
    }
    names.update(
        task.assigned_company.name
        for task in context.tasks
        if task.assigned_company and normalize_text(task.assigned_company.name)
    )
    return sorted(names)


def task_line(task: ProjectTask) -> str:
    company = task.assigned_company.name if task.assigned_company else "azienda non assegnata"
    status_bits = [f"{task.progress}%"]
    if task.alert:
        status_bits.append("alert")
    if task.date_completed:
        status_bits.append(f"chiusa il {task.date_completed}")
    return (
        f"{task.name}: {format_date(task.date_start)} -> {format_date(task.date_end)}, "
        f"{company}, {', '.join(status_bits)}"
    )


def activity_line(activity: ProjectActivity) -> str:
    workers = ", ".join(worker.member_name for worker in activity.workers.all()) or "N/A"
    return (
        f"{activity.title}: task {activity.task.name}, {activity.get_status_display()}, "
        f"{format_date(activity.datetime_start)} -> {format_date(activity.datetime_end)}, "
        f"workers: {workers}"
    )


def post_line(post: ProjectPost) -> str:
    task_label = post.task.name if post.task else "N/A"
    activity_label = post.activity.title if post.activity else "N/A"
    return (
        f"{format_date(post.published_date)} - {post.get_post_kind_display()} "
        f"su task {task_label}, attivita {activity_label}: {truncate_text(post.text, 180)}"
    )


def build_overview_page(context: ProjectWikiContext) -> WikiPageDraft:
    project = context.project
    open_alert_posts = [post for post in context.posts if post.alert]
    alert_tasks = [task for task in context.tasks if task.alert]
    alert_activities = [activity for activity in context.activities if activity.alert]
    companies = company_names(context)
    closed_tasks = [task for task in context.tasks if task.date_completed or task.progress >= 100]
    body_lines = [
        "# Overview progetto",
        "",
        f"Progetto: {project.name}",
        f"Descrizione: {project.description or 'N/A'}",
        f"Indirizzo: {project.address or 'N/A'}",
        f"Finestra: {project.date_start} -> {project.date_end or 'N/A'}",
        f"Workspace titolare: {project.workspace.name}",
        "",
        "## Stato compilato",
        f"- Avanzamento medio task: {average_task_progress(context.tasks)}%",
        f"- Task: {len(context.tasks)} totali, {len(closed_tasks)} chiusi o al 100%",
        f"- Attivita: {len(context.activities)} totali",
        f"- Team: {len(context.members)} persone attive",
        f"- Aziende/workspace coinvolti: {len(companies)}",
        f"- Documenti registrati: {len(context.documents)}",
        (
            "- Criticita/alert aperti: "
            f"{len(open_alert_posts)} post, {len(alert_tasks)} task, {len(alert_activities)} attivita"
        ),
        "",
        "## Segnali principali",
        *markdown_list(
            [task_line(task) for task in context.tasks[:8]],
            "Nessun task disponibile nella memoria compilata.",
        ),
    ]
    refs = [
        project_source_ref(project),
        *[task_source_ref(task) for task in context.tasks[:12]],
        *[post_source_ref(post) for post in open_alert_posts[:8]],
        *[member_source_ref(member) for member in context.members[:12]],
        *[document_source_ref(document) for document in context.documents[:8]],
    ]
    return WikiPageDraft(
        slug="overview",
        page_type=AssistantWikiPageType.OVERVIEW,
        title="Overview progetto",
        body_markdown="\n".join(body_lines).strip(),
        summary=(
            f"{project.name}: {average_task_progress(context.tasks)}% medio sui task, "
            f"{len(open_alert_posts)} alert da post, {len(context.documents)} documenti."
        ),
        source_refs=dedupe_source_refs(refs),
        metadata={
            "task_count": len(context.tasks),
            "activity_count": len(context.activities),
            "document_count": len(context.documents),
            "team_member_count": len(context.members),
            "company_count": len(companies),
            "open_alert_post_count": len(open_alert_posts),
        },
    )


def build_timeline_page(context: ProjectWikiContext) -> WikiPageDraft:
    events = sorted(
        [
            *[(task.date_start, f"Task avviato: {task_line(task)}", task_source_ref(task)) for task in context.tasks],
            *[
                (task.date_end, f"Fine prevista task: {task.name}", task_source_ref(task))
                for task in context.tasks
            ],
            *[
                (
                    activity.datetime_start,
                    f"Attivita pianificata: {activity_line(activity)}",
                    activity_source_ref(activity),
                )
                for activity in context.activities
            ],
            *[(post.published_date, post_line(post), post_source_ref(post)) for post in context.posts],
            *[
                (
                    document.updated_at,
                    f"Documento aggiornato: {document.title}",
                    document_source_ref(document),
                )
                for document in context.documents
            ],
        ],
        key=lambda item: str(item[0] or ""),
    )
    body_lines = [
        "# Timeline compilata",
        "",
        "## Eventi ordinati",
        *markdown_list([f"{format_date(value)} - {label}" for value, label, _ref in events[:80]], "Nessun evento."),
    ]
    return WikiPageDraft(
        slug="timeline",
        page_type=AssistantWikiPageType.TIMELINE,
        title="Timeline compilata",
        body_markdown="\n".join(body_lines).strip(),
        summary=f"Timeline con {len(events)} eventi tra task, attivita, post e documenti.",
        source_refs=dedupe_source_refs([ref for _value, _label, ref in events]),
        metadata={"event_count": len(events)},
    )


def build_open_issues_page(context: ProjectWikiContext) -> WikiPageDraft:
    open_posts = [post for post in context.posts if post.alert]
    alert_tasks = [task for task in context.tasks if task.alert]
    alert_activities = [activity for activity in context.activities if activity.alert]
    body_lines = [
        "# Open issues",
        "",
        "## Post e segnalazioni aperte",
        *markdown_list([post_line(post) for post in open_posts], "Nessuna segnalazione aperta da post."),
        "",
        "## Task in alert",
        *markdown_list([task_line(task) for task in alert_tasks], "Nessun task in alert."),
        "",
        "## Attivita in alert",
        *markdown_list([activity_line(activity) for activity in alert_activities], "Nessuna attivita in alert."),
    ]
    refs = [
        *[post_source_ref(post) for post in open_posts],
        *[task_source_ref(task) for task in alert_tasks],
        *[activity_source_ref(activity) for activity in alert_activities],
    ]
    return WikiPageDraft(
        slug="open-issues",
        page_type=AssistantWikiPageType.OPEN_ISSUES,
        title="Open issues",
        body_markdown="\n".join(body_lines).strip(),
        summary=(
            f"{len(open_posts)} post aperti, {len(alert_tasks)} task in alert, "
            f"{len(alert_activities)} attivita in alert."
        ),
        source_refs=dedupe_source_refs(refs),
        metadata={
            "open_post_count": len(open_posts),
            "alert_task_count": len(alert_tasks),
            "alert_activity_count": len(alert_activities),
        },
    )


def build_decisions_page(context: ProjectWikiContext) -> WikiPageDraft:
    decision_posts = [
        post
        for post in context.posts
        if (
            post.post_kind == PostKind.ISSUE
            and not post.alert
        )
        or any(marker in compact_whitespace(post.text).lower() for marker in DECISION_MARKERS)
    ]
    body_lines = [
        "# Decisioni e chiusure",
        "",
        "Questa pagina raccoglie decisioni esplicite, validazioni e issue chiuse trovate nei post.",
        "",
        "## Evidenze",
        *markdown_list([post_line(post) for post in decision_posts], "Nessuna decisione esplicita trovata."),
    ]
    return WikiPageDraft(
        slug="decisions",
        page_type=AssistantWikiPageType.DECISIONS,
        title="Decisioni e chiusure",
        body_markdown="\n".join(body_lines).strip(),
        summary=f"{len(decision_posts)} decisioni, validazioni o chiusure candidate.",
        source_refs=dedupe_source_refs([post_source_ref(post) for post in decision_posts]),
        metadata={"decision_candidate_count": len(decision_posts)},
    )


def build_risks_page(context: ProjectWikiContext) -> WikiPageDraft:
    alert_posts = [post for post in context.posts if post.alert]
    alert_tasks = [task for task in context.tasks if task.alert]
    blocked_activities = [
        activity
        for activity in context.activities
        if activity.alert or activity.status != TaskActivityStatus.COMPLETED
    ]
    body_lines = [
        "# Rischi",
        "",
        "## Rischi da segnalazioni",
        *markdown_list([post_line(post) for post in alert_posts], "Nessuna segnalazione di rischio da post."),
        "",
        "## Rischi da task",
        *markdown_list([task_line(task) for task in alert_tasks], "Nessun task marcato in alert."),
        "",
        "## Attivita non chiuse o sensibili",
        *markdown_list(
            [activity_line(activity) for activity in blocked_activities[:30]],
            "Nessuna attivita sensibile rilevata.",
        ),
    ]
    refs = [
        *[post_source_ref(post) for post in alert_posts],
        *[task_source_ref(task) for task in alert_tasks],
        *[activity_source_ref(activity) for activity in blocked_activities],
    ]
    return WikiPageDraft(
        slug="risks",
        page_type=AssistantWikiPageType.RISKS,
        title="Rischi",
        body_markdown="\n".join(body_lines).strip(),
        summary=(
            f"{len(alert_posts)} segnalazioni, {len(alert_tasks)} task in alert, "
            f"{len(blocked_activities)} attivita non chiuse o sensibili."
        ),
        source_refs=dedupe_source_refs(refs),
        metadata={
            "risk_post_count": len(alert_posts),
            "risk_task_count": len(alert_tasks),
            "sensitive_activity_count": len(blocked_activities),
        },
    )


def build_documents_page(context: ProjectWikiContext) -> WikiPageDraft:
    body_lines = [
        "# Documenti",
        "",
        f"Documenti registrati: {len(context.documents)}",
        "",
        "## Registro",
        *markdown_list(
            [
                (
                    f"{document.title}: cartella {document.folder.name if document.folder else 'N/A'}, "
                    f"tipo {document.document_kind}, pubblico {'si' if document.is_public else 'no'}, "
                    f"descrizione: {document.description or 'N/A'}"
                )
                for document in context.documents
            ],
            "Nessun documento registrato.",
        ),
    ]
    return WikiPageDraft(
        slug="documents",
        page_type=AssistantWikiPageType.DOCUMENTS,
        title="Documenti",
        body_markdown="\n".join(body_lines).strip(),
        summary=f"{len(context.documents)} documenti nella memoria compilata.",
        source_refs=dedupe_source_refs([document_source_ref(document) for document in context.documents]),
        metadata={"document_count": len(context.documents)},
    )


def build_companies_page(context: ProjectWikiContext) -> WikiPageDraft:
    companies = company_names(context)
    task_by_company: dict[str, list[str]] = {}
    for task in context.tasks:
        name = task.assigned_company.name if task.assigned_company else "azienda non assegnata"
        task_by_company.setdefault(name, []).append(task.name)
    body_lines = [
        "# Aziende",
        "",
        f"Aziende/workspace coinvolti: {len(companies)}",
        "",
        "## Elenco",
        *markdown_list(companies, "Nessuna azienda/workspace rilevata."),
        "",
        "## Task per azienda",
        *markdown_list(
            [f"{name}: {', '.join(tasks)}" for name, tasks in sorted(task_by_company.items())],
            "Nessun task assegnato ad aziende.",
        ),
    ]
    refs = [
        *[member_source_ref(member) for member in context.members],
        *[task_source_ref(task) for task in context.tasks if task.assigned_company],
    ]
    return WikiPageDraft(
        slug="companies",
        page_type=AssistantWikiPageType.COMPANIES,
        title="Aziende",
        body_markdown="\n".join(body_lines).strip(),
        summary=f"{len(companies)} aziende/workspace coinvolti.",
        source_refs=dedupe_source_refs(refs),
        metadata={"company_count": len(companies), "companies": companies[:40]},
    )


def build_people_page(context: ProjectWikiContext) -> WikiPageDraft:
    body_lines = [
        "# Persone",
        "",
        f"Persone attive: {len(context.members)}",
        "",
        "## Team",
        *markdown_list(
            [
                (
                    f"{member.profile.member_name}: {member.get_role_display()}, "
                    f"{member.profile.workspace.name}, posizione {member.profile.position or 'N/A'}, "
                    f"esterno {'si' if member.is_external else 'no'}"
                )
                for member in context.members
            ],
            "Nessun membro attivo.",
        ),
    ]
    return WikiPageDraft(
        slug="people",
        page_type=AssistantWikiPageType.PEOPLE,
        title="Persone",
        body_markdown="\n".join(body_lines).strip(),
        summary=f"{len(context.members)} persone attive nel progetto.",
        source_refs=dedupe_source_refs([member_source_ref(member) for member in context.members]),
        metadata={"team_member_count": len(context.members)},
    )


def build_tasks_page(context: ProjectWikiContext) -> WikiPageDraft:
    body_lines = [
        "# Task",
        "",
        f"Task totali: {len(context.tasks)}",
        "",
        "## Elenco task",
        *markdown_list([task_line(task) for task in context.tasks], "Nessun task disponibile."),
    ]
    return WikiPageDraft(
        slug="tasks",
        page_type=AssistantWikiPageType.TASKS,
        title="Task",
        body_markdown="\n".join(body_lines).strip(),
        summary=f"{len(context.tasks)} task, avanzamento medio {average_task_progress(context.tasks)}%.",
        source_refs=dedupe_source_refs([task_source_ref(task) for task in context.tasks]),
        metadata={"task_count": len(context.tasks), "average_progress": average_task_progress(context.tasks)},
    )


def build_activities_page(context: ProjectWikiContext) -> WikiPageDraft:
    body_lines = [
        "# Attivita",
        "",
        f"Attivita totali: {len(context.activities)}",
        "",
        "## Elenco attivita",
        *markdown_list(
            [activity_line(activity) for activity in context.activities[:120]],
            "Nessuna attivita disponibile.",
        ),
    ]
    return WikiPageDraft(
        slug="activities",
        page_type=AssistantWikiPageType.ACTIVITIES,
        title="Attivita",
        body_markdown="\n".join(body_lines).strip(),
        summary=f"{len(context.activities)} attivita nella memoria compilata.",
        source_refs=dedupe_source_refs(
            [activity_source_ref(activity) for activity in context.activities],
        ),
        metadata={"activity_count": len(context.activities)},
    )


def build_project_wiki_drafts(context: ProjectWikiContext) -> list[WikiPageDraft]:
    return [
        build_overview_page(context),
        build_timeline_page(context),
        build_open_issues_page(context),
        build_decisions_page(context),
        build_risks_page(context),
        build_documents_page(context),
        build_companies_page(context),
        build_people_page(context),
        build_tasks_page(context),
        build_activities_page(context),
    ]


def page_content_hash(draft: WikiPageDraft) -> str:
    return sha256_text(
        json_dumps(
            {
                "slug": draft.slug,
                "title": draft.title,
                "body_markdown": draft.body_markdown,
                "summary": draft.summary,
                "source_refs": draft.source_refs,
                "metadata": draft.metadata,
                "schema_version": PROJECT_WIKI_SCHEMA_VERSION,
            }
        )
    )


def rebuild_project_wiki(project: Project, *, force: bool = False) -> list[ProjectAssistantWikiPage]:
    context = collect_project_wiki_context(project)
    current_version = project_wiki_version(context)
    drafts = build_project_wiki_drafts(context)
    now = timezone.now()
    pages: list[ProjectAssistantWikiPage] = []
    with transaction.atomic():
        for draft in drafts:
            content_hash = page_content_hash(draft)
            page, created = ProjectAssistantWikiPage.objects.get_or_create(
                project=project,
                slug=draft.slug,
                defaults={
                    "page_type": draft.page_type,
                    "title": draft.title,
                    "body_markdown": draft.body_markdown,
                    "summary": draft.summary,
                    "source_refs": draft.source_refs,
                    "metadata": draft.metadata,
                    "content_hash": content_hash,
                    "schema_version": PROJECT_WIKI_SCHEMA_VERSION,
                    "generated_version": current_version,
                    "generated_at": now,
                    "is_stale": False,
                },
            )
            if created:
                pages.append(page)
                continue
            should_update = (
                force
                or page.content_hash != content_hash
                or page.schema_version != PROJECT_WIKI_SCHEMA_VERSION
                or page.is_stale
                or page.generated_version != current_version
            )
            if should_update:
                page.page_type = draft.page_type
                page.title = draft.title
                page.body_markdown = draft.body_markdown
                page.summary = draft.summary
                page.source_refs = draft.source_refs
                page.metadata = draft.metadata
                page.content_hash = content_hash
                page.schema_version = PROJECT_WIKI_SCHEMA_VERSION
                page.generated_version = current_version
                page.generated_at = now
                page.is_stale = False
                page.save(
                    update_fields=[
                        "page_type",
                        "title",
                        "body_markdown",
                        "summary",
                        "source_refs",
                        "metadata",
                        "content_hash",
                        "schema_version",
                        "generated_version",
                        "generated_at",
                        "is_stale",
                    ]
                )
            pages.append(page)
        ProjectAssistantWikiPage.objects.filter(project=project).exclude(
            slug__in=[draft.slug for draft in drafts],
        ).update(is_stale=True)
    return pages


def ensure_project_wiki_pages(project: Project) -> list[ProjectAssistantWikiPage]:
    queryset = ProjectAssistantWikiPage.objects.filter(project=project)
    missing_pages = queryset.count() < len(AssistantWikiPageType.values)
    has_stale_pages = queryset.filter(is_stale=True).exists()
    has_old_schema = queryset.exclude(schema_version=PROJECT_WIKI_SCHEMA_VERSION).exists()
    if missing_pages or has_stale_pages or has_old_schema:
        return rebuild_project_wiki(project)
    return list(queryset.order_by("slug", "id"))


def render_project_wiki_index(project: Project, pages: list[ProjectAssistantWikiPage]) -> str:
    lines = [
        f"# Wiki progetto - {project.name}",
        "",
        "Questa cartella e un export Markdown della wiki DB primaria dell'assistant.",
        "Il DB resta la fonte autorevole; i file servono per audit, review e lettura umana.",
        "",
        "## Pagine",
    ]
    for page in sorted(pages, key=lambda item: item.slug):
        lines.append(f"- [{page.title}](./{page.slug}.md): {truncate_text(page.summary, 180)}")
    return "\n".join(lines).strip() + "\n"


def render_project_wiki_page_export(page: ProjectAssistantWikiPage) -> str:
    source_lines = []
    for source_ref in list(page.source_refs or [])[:80]:
        label = source_ref.get("label") or source_ref.get("source_key") or "Fonte"
        source_type = source_ref.get("source_type") or "source"
        source_key = source_ref.get("source_key") or ""
        source_lines.append(f"- [{source_type}] {label} (`{source_key}`)")
    if not source_lines:
        source_lines = ["- Nessuna fonte puntuale registrata."]
    metadata_block = json_dumps(
        {
            "slug": page.slug,
            "page_type": page.page_type,
            "schema_version": page.schema_version,
            "generated_version": page.generated_version,
            "generated_at": page.generated_at.isoformat() if page.generated_at else None,
            "content_hash": page.content_hash,
            "metadata": page.metadata,
        }
    )
    return "\n".join(
        [
            "---",
            metadata_block,
            "---",
            "",
            page.body_markdown.strip(),
            "",
            "## Provenance",
            *source_lines,
            "",
        ]
    )


def export_project_wiki_markdown(
    project: Project,
    *,
    output_dir: str | Path | None = None,
    rebuild: bool = False,
) -> list[Path]:
    pages = rebuild_project_wiki(project, force=True) if rebuild else ensure_project_wiki_pages(project)
    base_dir = Path(output_dir) if output_dir else Path(settings.BASE_DIR) / "docs" / "project-wiki"
    target_dir = base_dir / f"project-{project.id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    index_path = target_dir / "index.md"
    index_path.write_text(render_project_wiki_index(project, pages), encoding="utf-8")
    written_paths.append(index_path)
    for page in pages:
        page_path = target_dir / f"{page.slug}.md"
        page_path.write_text(render_project_wiki_page_export(page), encoding="utf-8")
        written_paths.append(page_path)
    return written_paths
