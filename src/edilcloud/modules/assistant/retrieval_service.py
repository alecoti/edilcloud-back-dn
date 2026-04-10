from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from edilcloud.modules.assistant.query_router import AssistantQueryRoute


TASK_ID_RE = re.compile(r"\btask\s*#?\s*(?P<task_id>\d+)\b", re.IGNORECASE)
ACTIVITY_ID_RE = re.compile(r"\battivita\s*#?\s*(?P<activity_id>\d+)\b", re.IGNORECASE)


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def compact_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", normalize_text(value))


@dataclass(slots=True)
class AssistantRetrievalContext:
    task_id: int | None = None
    activity_id: int | None = None
    source_types: list[str] = field(default_factory=list)
    context_scope: str = "project"
    strict_context: bool = False
    reasoning: list[str] = field(default_factory=list)


def parse_explicit_context_ids(question: str) -> tuple[int | None, int | None]:
    task_match = TASK_ID_RE.search(question or "")
    activity_match = ACTIVITY_ID_RE.search(question or "")
    task_id = int(task_match.group("task_id")) if task_match else None
    activity_id = int(activity_match.group("activity_id")) if activity_match else None
    return task_id, activity_id


def extract_last_context_from_citations(recent_messages: list[Any]) -> tuple[int | None, int | None]:
    for message in reversed(recent_messages):
        citations = list(getattr(message, "citations", []) or [])
        task_ids = {
            int(metadata.get("task_id"))
            for citation in citations
            if isinstance((metadata := citation.get("metadata")), dict) and metadata.get("task_id")
        }
        activity_ids = {
            int(metadata.get("activity_id"))
            for citation in citations
            if isinstance((metadata := citation.get("metadata")), dict) and metadata.get("activity_id")
        }
        if len(activity_ids) == 1 or len(task_ids) == 1:
            return (next(iter(task_ids), None), next(iter(activity_ids), None))
    return None, None


def derive_retrieval_context(
    *,
    question: str,
    route: AssistantQueryRoute,
    thread_metadata: dict[str, Any] | None,
    recent_messages: list[Any],
    explicit_task_id: int | None = None,
    explicit_activity_id: int | None = None,
) -> AssistantRetrievalContext:
    reasoning: list[str] = []
    parsed_task_id, parsed_activity_id = parse_explicit_context_ids(question)
    task_id = explicit_task_id or parsed_task_id
    activity_id = explicit_activity_id or parsed_activity_id

    if task_id:
        reasoning.append("explicit_task_context")
    if activity_id:
        reasoning.append("explicit_activity_context")

    if task_id is None and activity_id is None:
        last_context = (thread_metadata or {}).get("last_context") if isinstance(thread_metadata, dict) else {}
        if isinstance(last_context, dict):
            thread_task_id = last_context.get("task_id")
            thread_activity_id = last_context.get("activity_id")
            if thread_task_id:
                task_id = int(thread_task_id)
                reasoning.append("thread_task_context")
            if thread_activity_id:
                activity_id = int(thread_activity_id)
                reasoning.append("thread_activity_context")

    if task_id is None and activity_id is None and route.follow_up:
        inferred_task_id, inferred_activity_id = extract_last_context_from_citations(recent_messages)
        if inferred_task_id:
            task_id = inferred_task_id
            reasoning.append("follow_up_task_context")
        if inferred_activity_id:
            activity_id = inferred_activity_id
            reasoning.append("follow_up_activity_context")

    if activity_id is not None:
        context_scope = f"activity:{activity_id}"
    elif task_id is not None:
        context_scope = f"task:{task_id}"
    else:
        context_scope = "project"

    strict_context = context_scope != "project" and route.strategy in {
        "semantic_retrieval",
        "hybrid_db_retrieval",
        "deterministic_db",
    }

    return AssistantRetrievalContext(
        task_id=task_id,
        activity_id=activity_id,
        source_types=list(route.selected_source_types),
        context_scope=context_scope,
        strict_context=strict_context,
        reasoning=reasoning,
    )


def source_matches_context(source_document: Any, context: AssistantRetrievalContext) -> bool:
    metadata = getattr(source_document, "metadata", {}) or {}
    source_type = getattr(source_document, "source_type", None)
    task_id = metadata.get("task_id")
    activity_id = metadata.get("activity_id")

    if context.source_types and source_type not in set(context.source_types):
        if source_type not in {"project", "team_directory"}:
            return False

    if context.activity_id is not None:
        if activity_id == context.activity_id:
            return True
        if not context.strict_context and task_id == context.task_id:
            return True
        return source_type in {"project"}

    if context.task_id is not None:
        if task_id == context.task_id:
            return True
        return source_type in {"project"}

    return True


def filter_source_documents_for_context(source_documents: list[Any], context: AssistantRetrievalContext) -> list[Any]:
    filtered = [item for item in source_documents if source_matches_context(item, context)]
    return filtered or source_documents


def summarize_thread_context_from_citations(citations: list[dict[str, Any]]) -> dict[str, int] | None:
    task_ids = [
        int(metadata["task_id"])
        for citation in citations
        if isinstance((metadata := citation.get("metadata")), dict) and metadata.get("task_id")
    ]
    activity_ids = [
        int(metadata["activity_id"])
        for citation in citations
        if isinstance((metadata := citation.get("metadata")), dict) and metadata.get("activity_id")
    ]
    payload: dict[str, int] = {}
    unique_task_ids = set(task_ids)
    unique_activity_ids = set(activity_ids)
    if len(unique_task_ids) == 1:
        payload["task_id"] = next(iter(unique_task_ids))
    if len(unique_activity_ids) == 1:
        payload["activity_id"] = next(iter(unique_activity_ids))
    return payload or None
