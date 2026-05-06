from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Any

from django.db import transaction
from django.utils import timezone

from edilcloud.modules.assistant.models import ProjectAssistantGraphSnapshot
from edilcloud.modules.assistant.wiki_service import (
    DECISION_MARKERS,
    ProjectWikiContext,
    activity_source_ref,
    collect_project_wiki_context,
    compact_whitespace,
    dedupe_source_refs,
    document_source_ref,
    format_date,
    json_dumps,
    member_source_ref,
    normalize_text,
    post_source_ref,
    project_source_ref,
    project_wiki_version,
    sha256_text,
    task_source_ref,
    truncate_text,
)
from edilcloud.modules.projects.models import (
    PostKind,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectMember,
    ProjectPost,
    ProjectTask,
)


PROJECT_GRAPH_SCHEMA_VERSION = "project-graph:v1"
RESOLUTION_MARKERS = (*DECISION_MARKERS, "risolt", "sbloccat")
GRAPH_TOKEN_RE = re.compile(r"[a-z0-9]{4,}", re.IGNORECASE)
GRAPH_STOPWORDS = {
    "alla",
    "alle",
    "allo",
    "anche",
    "avvio",
    "come",
    "con",
    "della",
    "delle",
    "degli",
    "demo",
    "documento",
    "dopo",
    "fase",
    "lavori",
    "lato",
    "nella",
    "nelle",
    "nello",
    "nota",
    "operativo",
    "prima",
    "progetto",
    "sul",
    "sulla",
    "task",
    "verbale",
}


@dataclass(slots=True)
class ProjectGraphDraft:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    summary_markdown: str
    source_refs: list[dict[str, Any]]
    metadata: dict[str, Any]
    content_hash: str
    generated_version: int


def project_node_id(project: Project) -> str:
    return f"project:{project.id}"


def company_node_id(company: Any) -> str:
    return f"company:{company.id}"


def person_node_id(member_or_profile: Any) -> str:
    profile_id = getattr(member_or_profile, "profile_id", None) or getattr(member_or_profile, "id", None)
    return f"person:{profile_id}"


def task_node_id(task: ProjectTask) -> str:
    return f"task:{task.id}"


def activity_node_id(activity: ProjectActivity) -> str:
    return f"activity:{activity.id}"


def document_node_id(document: ProjectDocument) -> str:
    return f"document:{document.id}"


def post_node_id(post: ProjectPost) -> str:
    return f"post:{post.id}"


def issue_node_id(post: ProjectPost) -> str:
    return f"issue:post:{post.id}"


def decision_node_id(post: ProjectPost) -> str:
    return f"decision:post:{post.id}"


def risk_node_id(entity_type: str, entity_id: int) -> str:
    return f"risk:{entity_type}:{entity_id}"


def clean_graph_metadata(values: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in values.items():
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            metadata[key] = value
        elif isinstance(value, int):
            metadata[key] = value
        elif isinstance(value, float):
            metadata[key] = round(value, 4)
        elif isinstance(value, str):
            normalized = normalize_text(value)
            if normalized:
                metadata[key] = truncate_text(normalized, 220)
        elif hasattr(value, "isoformat"):
            metadata[key] = str(value.isoformat())
        elif isinstance(value, list):
            clean_values: list[Any] = []
            for item in value:
                if item in (None, ""):
                    continue
                if isinstance(item, bool):
                    clean_values.append(item)
                elif isinstance(item, int):
                    clean_values.append(item)
                elif isinstance(item, float):
                    clean_values.append(round(item, 4))
                else:
                    clean_item = truncate_text(compact_whitespace(str(item)), 180)
                    if clean_item:
                        clean_values.append(clean_item)
            if clean_values:
                metadata[key] = clean_values[:24]
        elif isinstance(value, dict):
            normalized_dict = truncate_text(json_dumps(value), 500)
            if normalized_dict:
                metadata[key] = normalized_dict
    return metadata


def source_ref_keys(source_refs: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    for source_ref in source_refs:
        source_key = normalize_text(str(source_ref.get("source_key") or ""))
        if source_key:
            keys.append(source_key)
    return list(dict.fromkeys(keys))


def add_node(
    nodes_by_id: dict[str, dict[str, Any]],
    node_id: str,
    node_type: str,
    label: str,
    **metadata: Any,
) -> None:
    current = nodes_by_id.get(node_id)
    clean_metadata = clean_graph_metadata(metadata)
    if current is None:
        nodes_by_id[node_id] = {
            "id": node_id,
            "type": node_type,
            "label": truncate_text(label or node_id, 180),
            "metadata": clean_metadata,
        }
        return
    current["metadata"] = {**dict(current.get("metadata") or {}), **clean_metadata}


def add_edge(
    edges_by_key: dict[tuple[str, str, str], dict[str, Any]],
    source: str,
    target: str,
    edge_type: str,
    label: str,
    *,
    source_refs: list[dict[str, Any]] | None = None,
    **metadata: Any,
) -> None:
    refs = dedupe_source_refs(source_refs or [], limit=16)
    key = (source, target, edge_type)
    clean_metadata = clean_graph_metadata(
        {
            **metadata,
            "source_ref_keys": source_ref_keys(refs),
        }
    )
    current = edges_by_key.get(key)
    if current is None:
        edges_by_key[key] = {
            "source": source,
            "target": target,
            "type": edge_type,
            "label": truncate_text(label or edge_type, 160),
            "metadata": clean_metadata,
            "source_refs": refs,
        }
        return

    current["metadata"] = {**dict(current.get("metadata") or {}), **clean_metadata}
    current["source_refs"] = dedupe_source_refs(
        [*list(current.get("source_refs") or []), *refs],
        limit=16,
    )


def graph_tokens(value: str | None) -> set[str]:
    return {
        token.lower()
        for token in GRAPH_TOKEN_RE.findall(compact_whitespace(value).lower())
        if token.lower() not in GRAPH_STOPWORDS
    }


def overlap_score(left: str | None, right: str | None) -> int:
    return len(graph_tokens(left) & graph_tokens(right))


def post_title(post: ProjectPost) -> str:
    return truncate_text(post.text or f"Post {post.id}", 120)


def is_decision_post(post: ProjectPost) -> bool:
    text = compact_whitespace(post.text).lower()
    return (post.post_kind == PostKind.ISSUE and not post.alert) or any(
        marker in text for marker in RESOLUTION_MARKERS
    )


def entity_label(nodes_by_id: dict[str, dict[str, Any]], node_id: str) -> str:
    node = nodes_by_id.get(node_id) or {}
    return normalize_text(str(node.get("label") or node_id)) or node_id


def edge_line(edge: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> str:
    source = entity_label(nodes_by_id, str(edge.get("source") or ""))
    target = entity_label(nodes_by_id, str(edge.get("target") or ""))
    edge_type = normalize_text(str(edge.get("type") or "relates_to"))
    label = normalize_text(str(edge.get("label") or edge_type))
    source_keys = source_ref_keys(list(edge.get("source_refs") or []))[:3]
    evidence = f" Fonti: {', '.join(source_keys)}." if source_keys else ""
    return f"- [{edge_type} / {label}] {source} -> {target}.{evidence}"


def limited_edge_lines(
    edges: list[dict[str, Any]],
    nodes_by_id: dict[str, dict[str, Any]],
    edge_types: set[str],
    *,
    limit: int = 8,
) -> list[str]:
    selected = [edge for edge in edges if str(edge.get("type") or "") in edge_types][:limit]
    if not selected:
        return ["- Nessuna relazione esplicita disponibile."]
    return [edge_line(edge, nodes_by_id) for edge in selected]


def build_graph_summary(
    *,
    context: ProjectWikiContext,
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> str:
    node_counts = Counter(str(node.get("type") or "unknown") for node in nodes_by_id.values())
    edge_counts = Counter(str(edge.get("type") or "unknown") for edge in edges)
    lines = [
        "# Graph progetto",
        "",
        f"Schema: {PROJECT_GRAPH_SCHEMA_VERSION}",
        f"Progetto: {context.project.name}",
        f"Nodi: {len(nodes_by_id)}",
        f"Relazioni: {len(edges)}",
        "",
        "## Tipi principali",
        "- Nodi: "
        + ", ".join(f"{node_type}={count}" for node_type, count in sorted(node_counts.items())),
        "- Relazioni: "
        + ", ".join(f"{edge_type}={count}" for edge_type, count in sorted(edge_counts.items())),
        "",
        "## Relazioni operative",
        *limited_edge_lines(edges, nodes_by_id, {"works_on", "assigned_to", "has_activity"}, limit=10),
        "",
        "## Blocchi, rischi e decisioni",
        *limited_edge_lines(edges, nodes_by_id, {"blocks", "affects", "resolves"}, limit=12),
        "",
        "## Prove documentali",
        *limited_edge_lines(edges, nodes_by_id, {"supports", "reports_on", "recorded_by"}, limit=10),
    ]
    return "\n".join(lines).strip()


def build_project_graph_draft(context: ProjectWikiContext) -> ProjectGraphDraft:
    project = context.project
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    all_source_refs: list[dict[str, Any]] = [project_source_ref(project)]
    project_id = project_node_id(project)

    add_node(
        nodes_by_id,
        project_id,
        "project",
        project.name,
        project_id=project.id,
        workspace_name=project.workspace.name,
        date_start=project.date_start,
        date_end=project.date_end,
    )

    for member in context.members:
        member_ref = member_source_ref(member)
        all_source_refs.append(member_ref)
        company = member.profile.workspace
        company_id = company_node_id(company)
        profile_id = person_node_id(member)
        add_node(
            nodes_by_id,
            company_id,
            "company",
            company.name,
            workspace_id=company.id,
            workspace_name=company.name,
        )
        add_node(
            nodes_by_id,
            profile_id,
            "person",
            member.profile.member_name,
            member_id=member.id,
            profile_id=member.profile_id,
            role=member.get_role_display(),
            workspace_name=company.name,
            is_external=member.is_external,
        )
        add_edge(
            edges_by_key,
            project_id,
            company_id,
            "involves_company",
            "coinvolge azienda",
            source_refs=[member_ref],
        )
        add_edge(
            edges_by_key,
            profile_id,
            company_id,
            "works_for",
            "lavora per",
            source_refs=[member_ref],
        )
        add_edge(
            edges_by_key,
            profile_id,
            project_id,
            "member_of_project",
            "partecipa al progetto",
            source_refs=[member_ref],
        )

    for task in context.tasks:
        task_ref = task_source_ref(task)
        all_source_refs.append(task_ref)
        task_id = task_node_id(task)
        add_node(
            nodes_by_id,
            task_id,
            "task",
            task.name,
            task_id=task.id,
            progress=task.progress,
            alert=task.alert,
            date_start=task.date_start,
            date_end=task.date_end,
            date_completed=task.date_completed,
            note=task.note,
        )
        add_edge(edges_by_key, project_id, task_id, "has_task", "contiene task", source_refs=[task_ref])
        if task.assigned_company:
            company_id = company_node_id(task.assigned_company)
            add_node(
                nodes_by_id,
                company_id,
                "company",
                task.assigned_company.name,
                workspace_id=task.assigned_company.id,
                workspace_name=task.assigned_company.name,
            )
            add_edge(
                edges_by_key,
                company_id,
                task_id,
                "works_on",
                "lavora su",
                source_refs=[task_ref],
                task_id=task.id,
                company_name=task.assigned_company.name,
            )
        if task.alert:
            risk_id = risk_node_id("task", task.id)
            add_node(nodes_by_id, risk_id, "risk", f"Rischio task: {task.name}", task_id=task.id)
            add_edge(edges_by_key, risk_id, task_id, "affects", "impatta", source_refs=[task_ref])
            add_edge(edges_by_key, project_id, risk_id, "tracks_risk", "traccia rischio", source_refs=[task_ref])

    for activity in context.activities:
        activity_ref = activity_source_ref(activity)
        all_source_refs.append(activity_ref)
        activity_id = activity_node_id(activity)
        task_id = task_node_id(activity.task)
        add_node(
            nodes_by_id,
            activity_id,
            "activity",
            activity.title,
            activity_id=activity.id,
            task_id=activity.task_id,
            task_name=activity.task.name,
            status=activity.status,
            progress=activity.progress,
            alert=activity.alert,
            datetime_start=activity.datetime_start,
            datetime_end=activity.datetime_end,
            note=activity.note,
        )
        add_edge(
            edges_by_key,
            task_id,
            activity_id,
            "has_activity",
            "contiene attivita",
            source_refs=[activity_ref, task_source_ref(activity.task)],
            task_id=activity.task_id,
            activity_id=activity.id,
        )
        add_edge(
            edges_by_key,
            activity_id,
            task_id,
            "belongs_to_task",
            "appartiene alla task",
            source_refs=[activity_ref],
        )
        for worker in activity.workers.all():
            worker_id = person_node_id(worker)
            add_node(
                nodes_by_id,
                worker_id,
                "person",
                worker.member_name,
                profile_id=worker.id,
                workspace_name=worker.workspace.name,
            )
            add_edge(
                edges_by_key,
                worker_id,
                activity_id,
                "assigned_to",
                "assegnato a",
                source_refs=[activity_ref],
                activity_id=activity.id,
                task_id=activity.task_id,
            )
        if activity.alert:
            risk_id = risk_node_id("activity", activity.id)
            add_node(
                nodes_by_id,
                risk_id,
                "risk",
                f"Rischio attivita: {activity.title}",
                activity_id=activity.id,
                task_id=activity.task_id,
            )
            add_edge(edges_by_key, risk_id, activity_id, "affects", "impatta", source_refs=[activity_ref])
            add_edge(edges_by_key, risk_id, task_id, "affects", "impatta", source_refs=[activity_ref])

    for document in context.documents:
        document_ref = document_source_ref(document)
        all_source_refs.append(document_ref)
        doc_id = document_node_id(document)
        doc_text = f"{document.title} {document.description} {document.folder.name if document.folder else ''}"
        add_node(
            nodes_by_id,
            doc_id,
            "document",
            document.title or f"Documento {document.id}",
            document_id=document.id,
            folder_name=document.folder.name if document.folder else None,
            document_kind=document.document_kind,
            description=document.description,
        )
        add_edge(edges_by_key, doc_id, project_id, "supports", "supporta", source_refs=[document_ref])
        for task in context.tasks:
            score = overlap_score(doc_text, f"{task.name} {task.note}")
            if score >= 2:
                add_edge(
                    edges_by_key,
                    doc_id,
                    task_node_id(task),
                    "supports",
                    "supporta task",
                    source_refs=[document_ref, task_source_ref(task)],
                    overlap_score=score,
                )
        for activity in context.activities:
            score = overlap_score(doc_text, f"{activity.title} {activity.description} {activity.note} {activity.task.name}")
            if score >= 2:
                add_edge(
                    edges_by_key,
                    doc_id,
                    activity_node_id(activity),
                    "supports",
                    "supporta attivita",
                    source_refs=[document_ref, activity_source_ref(activity)],
                    overlap_score=score,
                )

    for post in context.posts:
        post_ref = post_source_ref(post)
        all_source_refs.append(post_ref)
        post_id = post_node_id(post)
        add_node(
            nodes_by_id,
            post_id,
            "post",
            post_title(post),
            post_id=post.id,
            post_kind=post.post_kind,
            alert=post.alert,
            task_id=post.task_id,
            activity_id=post.activity_id,
            published_date=post.published_date,
        )
        target_id = project_id
        if post.activity:
            target_id = activity_node_id(post.activity)
        elif post.task:
            target_id = task_node_id(post.task)
        add_edge(edges_by_key, post_id, target_id, "reports_on", "segnala su", source_refs=[post_ref])

        if post.post_kind == PostKind.ISSUE or post.alert:
            issue_id = issue_node_id(post)
            add_node(
                nodes_by_id,
                issue_id,
                "issue",
                f"Issue: {post_title(post)}",
                post_id=post.id,
                task_id=post.task_id,
                activity_id=post.activity_id,
                alert=post.alert,
                issue_status="open" if post.alert else "resolved",
            )
            add_edge(edges_by_key, issue_id, post_id, "reported_by", "segnalata da", source_refs=[post_ref])
            if post.activity:
                add_edge(
                    edges_by_key,
                    issue_id,
                    activity_node_id(post.activity),
                    "blocks",
                    "blocca",
                    source_refs=[post_ref, activity_source_ref(post.activity)],
                    activity_id=post.activity_id,
                    task_id=post.task_id,
                )
            if post.task:
                add_edge(
                    edges_by_key,
                    issue_id,
                    task_node_id(post.task),
                    "blocks",
                    "blocca",
                    source_refs=[post_ref, task_source_ref(post.task)],
                    task_id=post.task_id,
                    activity_id=post.activity_id,
                )
            if not post.task and not post.activity:
                add_edge(edges_by_key, issue_id, project_id, "affects", "impatta", source_refs=[post_ref])

        if post.alert:
            risk_id = risk_node_id("post", post.id)
            add_node(
                nodes_by_id,
                risk_id,
                "risk",
                f"Rischio da post: {post_title(post)}",
                post_id=post.id,
                task_id=post.task_id,
                activity_id=post.activity_id,
            )
            add_edge(edges_by_key, risk_id, post_id, "derived_from", "deriva da", source_refs=[post_ref])
            add_edge(edges_by_key, risk_id, target_id, "affects", "impatta", source_refs=[post_ref])

        if is_decision_post(post):
            decision_id = decision_node_id(post)
            add_node(
                nodes_by_id,
                decision_id,
                "decision",
                f"Decisione: {post_title(post)}",
                post_id=post.id,
                task_id=post.task_id,
                activity_id=post.activity_id,
            )
            add_edge(edges_by_key, decision_id, post_id, "recorded_by", "registrata da", source_refs=[post_ref])
            add_edge(edges_by_key, decision_id, target_id, "resolves", "risolve", source_refs=[post_ref])

    nodes = sorted(nodes_by_id.values(), key=lambda item: (str(item.get("type") or ""), str(item.get("id") or "")))
    edges = sorted(
        edges_by_key.values(),
        key=lambda item: (str(item.get("type") or ""), str(item.get("source") or ""), str(item.get("target") or "")),
    )
    source_refs = dedupe_source_refs(all_source_refs, limit=120)
    metadata = {
        "schema_version": PROJECT_GRAPH_SCHEMA_VERSION,
        "project_id": project.id,
        "project_name": project.name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "node_type_counts": dict(Counter(str(node.get("type") or "unknown") for node in nodes)),
        "edge_type_counts": dict(Counter(str(edge.get("type") or "unknown") for edge in edges)),
        "source_ref_count": len(source_refs),
    }
    summary_markdown = build_graph_summary(context=context, nodes_by_id=nodes_by_id, edges=edges)
    generated_version = project_wiki_version(context)
    content_hash = sha256_text(
        json_dumps(
            {
                "schema_version": PROJECT_GRAPH_SCHEMA_VERSION,
                "nodes": nodes,
                "edges": edges,
                "summary_markdown": summary_markdown,
                "source_refs": source_refs,
            }
        )
    )
    return ProjectGraphDraft(
        nodes=nodes,
        edges=edges,
        summary_markdown=summary_markdown,
        source_refs=source_refs,
        metadata=metadata,
        content_hash=content_hash,
        generated_version=generated_version,
    )


def rebuild_project_graph(project: Project, *, force: bool = False) -> ProjectAssistantGraphSnapshot:
    context = collect_project_wiki_context(project)
    draft = build_project_graph_draft(context)
    current = ProjectAssistantGraphSnapshot.objects.filter(project=project).first()
    if (
        current
        and not force
        and not current.is_stale
        and current.schema_version == PROJECT_GRAPH_SCHEMA_VERSION
        and current.content_hash == draft.content_hash
        and current.generated_version == draft.generated_version
    ):
        return current

    now = timezone.now()
    with transaction.atomic():
        snapshot, _created = ProjectAssistantGraphSnapshot.objects.select_for_update().get_or_create(project=project)
        snapshot.nodes = draft.nodes
        snapshot.edges = draft.edges
        snapshot.summary_markdown = draft.summary_markdown
        snapshot.source_refs = draft.source_refs
        snapshot.metadata = draft.metadata
        snapshot.content_hash = draft.content_hash
        snapshot.schema_version = PROJECT_GRAPH_SCHEMA_VERSION
        snapshot.generated_version = draft.generated_version
        snapshot.generated_at = now
        snapshot.is_stale = False
        snapshot.save(
            update_fields=[
                "nodes",
                "edges",
                "summary_markdown",
                "source_refs",
                "metadata",
                "content_hash",
                "schema_version",
                "generated_version",
                "generated_at",
                "is_stale",
                "updated_at",
            ]
        )
    return snapshot


def ensure_project_graph_snapshot(project: Project) -> ProjectAssistantGraphSnapshot:
    snapshot = ProjectAssistantGraphSnapshot.objects.filter(project=project).first()
    if (
        snapshot is None
        or snapshot.is_stale
        or snapshot.schema_version != PROJECT_GRAPH_SCHEMA_VERSION
    ):
        return rebuild_project_graph(project)
    return snapshot


def graph_edges_for_node(
    snapshot: ProjectAssistantGraphSnapshot,
    node_id: str,
    *,
    edge_type: str | None = None,
) -> list[dict[str, Any]]:
    edges = []
    for edge in list(snapshot.edges or []):
        if edge_type and edge.get("type") != edge_type:
            continue
        if edge.get("source") == node_id or edge.get("target") == node_id:
            edges.append(edge)
    return edges


def graph_snapshot_as_source_content(snapshot: ProjectAssistantGraphSnapshot) -> str:
    nodes_by_id = {str(node.get("id") or ""): node for node in list(snapshot.nodes or []) if node.get("id")}
    edge_lines = [
        edge_line(edge, nodes_by_id)
        for edge in list(snapshot.edges or [])[:160]
        if isinstance(edge, dict)
    ]
    node_lines = [
        f"- [{node.get('type')}] {node.get('label')} (`{node.get('id')}`)"
        for node in list(snapshot.nodes or [])[:80]
        if isinstance(node, dict)
    ]
    return "\n".join(
        [
            snapshot.summary_markdown,
            "",
            "## Catalogo relazioni indicizzato",
            *edge_lines,
            "",
            "## Nodi indicizzati",
            *node_lines,
        ]
    ).strip()
