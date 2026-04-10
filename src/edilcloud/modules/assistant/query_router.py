from __future__ import annotations

from dataclasses import dataclass, field
import re


COUNT_MARKERS = (
    "quanti",
    "quante",
    "numero",
    "totale",
    "count",
)
LIST_MARKERS = (
    "elenco",
    "lista",
    "quali sono",
    "chi sono",
    "fammi vedere",
    "mostrami",
)
COMPANY_MARKERS = (
    "azienda",
    "aziende",
    "impresa",
    "imprese",
    "ditta",
    "ditte",
    "workspace",
)
TEAM_MARKERS = (
    "team",
    "membri",
    "membro",
    "partecipanti",
    "partecipante",
    "persone",
    "profili",
    "chi lavora",
    "chi e coinvolto",
)
TASK_MARKERS = ("task", "attivita di lavoro", "lavorazioni")
ACTIVITY_MARKERS = ("attivita", "attivita'", "activity")
DOCUMENT_MARKERS = (
    "document",
    "allegat",
    "pdf",
    "verbale",
    "rapport",
    "giornale",
    "elaborat",
    "tavol",
    "disegn",
    "file",
)
TIMELINE_MARKERS = (
    "oggi",
    "ieri",
    "timeline",
    "cronologia",
    "ultimi",
    "settimana",
    "giorni",
    "mese",
    "quando",
    "cosa e successo",
    "cosa e' successo",
)
ALERT_MARKERS = (
    "critic",
    "alert",
    "issue",
    "segnal",
    "proble",
    "anom",
    "risch",
    "blocc",
)
RESOLVED_MARKERS = ("risolt", "chius", "closed", "completamente risolte")
SUMMARY_MARKERS = (
    "riepilogo",
    "riassunto",
    "sintesi",
    "panoramica",
    "situazione",
    "stato progetto",
    "stato del cantiere",
    "aggiornami",
)
FOLLOW_UP_PREFIXES = (
    "e ",
    "e per",
    "e quella",
    "e quelle",
    "e quello",
    "e invece",
    "invece",
    "poi",
    "ok",
    "bene",
)
TIME_RANGE_RE = re.compile(r"\bultimi\s+(?P<count>\d{1,2})\s+giorni\b", re.IGNORECASE)


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def compact_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", normalize_text(value))


def contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = compact_whitespace(text).lower()
    return any(marker in lowered for marker in markers)


@dataclass(slots=True)
class AssistantQueryRoute:
    intent: str
    strategy: str
    selected_source_types: list[str] = field(default_factory=list)
    temporal_scope: str | None = None
    follow_up: bool = False
    reasoning: list[str] = field(default_factory=list)


def question_looks_follow_up(question: str) -> bool:
    lowered = compact_whitespace(question).lower()
    if not lowered:
        return False
    return any(lowered.startswith(prefix) for prefix in FOLLOW_UP_PREFIXES) or len(lowered.split()) <= 5


def detect_temporal_scope(question: str) -> str | None:
    lowered = compact_whitespace(question).lower()
    if "oggi" in lowered:
        return "today"
    if "ieri" in lowered:
        return "yesterday"
    if "settimana scorsa" in lowered:
        return "last_week"
    if TIME_RANGE_RE.search(lowered):
        return "rolling_days"
    if contains_any(lowered, TIMELINE_MARKERS):
        return "timeline"
    return None


def default_source_types_for_intent(intent: str) -> list[str]:
    mapping = {
        "project_summary": ["project", "task", "activity", "post", "comment", "document"],
        "company_count": ["project", "team_directory", "task"],
        "company_list": ["project", "team_directory", "task"],
        "team_count": ["team_directory"],
        "team_list": ["team_directory"],
        "task_count": ["task"],
        "task_list": ["task"],
        "task_status": ["task", "activity", "post"],
        "activity_by_date": ["activity", "post", "comment"],
        "timeline_summary": ["activity", "post", "comment", "document", "photo"],
        "open_alerts": ["open_alerts_summary", "post", "task", "activity"],
        "resolved_issues": ["resolved_issues_summary", "post", "task", "activity"],
        "document_list": ["documents_catalog", "document"],
        "document_search": ["document", "documents_catalog", "post_attachment", "comment_attachment"],
        "generic_semantic": ["document", "post", "comment", "post_attachment", "comment_attachment"],
    }
    return list(mapping.get(intent, ["project", "document", "post", "comment"]))


def classify_assistant_query(question: str) -> AssistantQueryRoute:
    lowered = compact_whitespace(question).lower()
    reasoning: list[str] = []
    follow_up = question_looks_follow_up(question)
    temporal_scope = detect_temporal_scope(question)

    asks_count = contains_any(lowered, COUNT_MARKERS)
    asks_list = contains_any(lowered, LIST_MARKERS)
    mentions_companies = contains_any(lowered, COMPANY_MARKERS)
    mentions_team = contains_any(lowered, TEAM_MARKERS)
    mentions_tasks = contains_any(lowered, TASK_MARKERS)
    mentions_activities = contains_any(lowered, ACTIVITY_MARKERS)
    mentions_documents = contains_any(lowered, DOCUMENT_MARKERS)
    mentions_alerts = contains_any(lowered, ALERT_MARKERS)
    mentions_resolved = contains_any(lowered, RESOLVED_MARKERS)
    mentions_summary = contains_any(lowered, SUMMARY_MARKERS)
    mentions_timeline = temporal_scope is not None

    if mentions_alerts:
        reasoning.append("query_alert_like")
        intent = "resolved_issues" if mentions_resolved else "open_alerts"
        strategy = "deterministic_db"
        return AssistantQueryRoute(
            intent=intent,
            strategy=strategy,
            selected_source_types=default_source_types_for_intent(intent),
            temporal_scope=temporal_scope,
            follow_up=follow_up,
            reasoning=reasoning,
        )

    if mentions_documents:
        reasoning.append("query_document_like")
        intent = "document_list" if asks_count or asks_list else "document_search"
        strategy = "deterministic_db" if intent == "document_list" else "semantic_retrieval"
        return AssistantQueryRoute(
            intent=intent,
            strategy=strategy,
            selected_source_types=default_source_types_for_intent(intent),
            temporal_scope=temporal_scope,
            follow_up=follow_up,
            reasoning=reasoning,
        )

    if mentions_companies:
        reasoning.append("query_company_like")
        intent = "company_count" if asks_count else "company_list"
        return AssistantQueryRoute(
            intent=intent,
            strategy="deterministic_db",
            selected_source_types=default_source_types_for_intent(intent),
            temporal_scope=temporal_scope,
            follow_up=follow_up,
            reasoning=reasoning,
        )

    if mentions_team:
        reasoning.append("query_team_like")
        intent = "team_count" if asks_count and not asks_list else "team_list"
        return AssistantQueryRoute(
            intent=intent,
            strategy="deterministic_db",
            selected_source_types=default_source_types_for_intent(intent),
            temporal_scope=temporal_scope,
            follow_up=follow_up,
            reasoning=reasoning,
        )

    if mentions_timeline and (mentions_activities or "oggi" in lowered or "ieri" in lowered):
        reasoning.append("query_activity_by_date")
        return AssistantQueryRoute(
            intent="activity_by_date",
            strategy="deterministic_db",
            selected_source_types=default_source_types_for_intent("activity_by_date"),
            temporal_scope=temporal_scope,
            follow_up=follow_up,
            reasoning=reasoning,
        )

    if mentions_timeline:
        reasoning.append("query_timeline_like")
        return AssistantQueryRoute(
            intent="timeline_summary",
            strategy="hybrid_db_retrieval",
            selected_source_types=default_source_types_for_intent("timeline_summary"),
            temporal_scope=temporal_scope,
            follow_up=follow_up,
            reasoning=reasoning,
        )

    if mentions_tasks:
        reasoning.append("query_task_like")
        if asks_count:
            intent = "task_count"
        elif asks_list:
            intent = "task_list"
        else:
            intent = "task_status"
        return AssistantQueryRoute(
            intent=intent,
            strategy="deterministic_db",
            selected_source_types=default_source_types_for_intent(intent),
            temporal_scope=temporal_scope,
            follow_up=follow_up,
            reasoning=reasoning,
        )

    if mentions_summary:
        reasoning.append("query_summary_like")
        return AssistantQueryRoute(
            intent="project_summary",
            strategy="hybrid_db_retrieval",
            selected_source_types=default_source_types_for_intent("project_summary"),
            temporal_scope=temporal_scope,
            follow_up=follow_up,
            reasoning=reasoning,
        )

    reasoning.append("query_fallback_semantic")
    return AssistantQueryRoute(
        intent="generic_semantic",
        strategy="semantic_retrieval",
        selected_source_types=default_source_types_for_intent("generic_semantic"),
        temporal_scope=temporal_scope,
        follow_up=follow_up,
        reasoning=reasoning,
    )
