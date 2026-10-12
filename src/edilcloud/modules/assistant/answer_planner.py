from __future__ import annotations

from dataclasses import dataclass, field
import re

from edilcloud.modules.assistant.models import AssistantResponseMode
from edilcloud.modules.assistant.query_router import AssistantQueryRoute


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def compact_whitespace(value: str | None) -> str:
    return re.sub(r"\s+", " ", normalize_text(value))


@dataclass(slots=True)
class AssistantAnswerPlan:
    target_length: str
    response_structure: str
    citation_density: str
    answer_mode: str
    answer_sections: list[str] = field(default_factory=list)
    reasoning: list[str] = field(default_factory=list)
    answerability: str = "answer"
    depth: str = "standard"
    presentation: str = "adaptive"
    evidence_policy: str = "claim_level"
    requirements: list[str] = field(default_factory=list)


AMBIGUOUS_REFERENCE_RE = re.compile(
    r"^(?:e\s+)?(?:quell[oaie]|quest[oaie])\b",
    re.IGNORECASE,
)
SHORT_PASSIVE_REFERENCE_RE = re.compile(
    r"^(?:e\s+)?(?:e|è)\s+stat[oaie]\b",
    re.IGNORECASE,
)


def needs_clarification(question: str, *, has_conversation_context: bool) -> bool:
    """Detect references that cannot be resolved safely on a fresh thread."""
    if has_conversation_context:
        return False
    compact = compact_whitespace(question)
    if AMBIGUOUS_REFERENCE_RE.search(compact):
        return True
    return bool(SHORT_PASSIVE_REFERENCE_RE.search(compact) and len(compact.split()) <= 4)


def infer_depth(question: str, route: AssistantQueryRoute) -> str:
    lowered = compact_whitespace(question).lower()
    if any(marker in lowered for marker in ("breve", "brevissimo", "in una riga", "in due righe", "sintetico")):
        return "compact"
    if route.intent in {"company_count", "team_count", "task_count"}:
        return "compact"
    if any(
        marker in lowered
        for marker in (
            "riferimento esatto",
            "codice esatto",
            "codice preciso",
            "qual e il codice",
            "qual è il codice",
            "quanti millimetri",
        )
    ):
        return "compact"
    if any(marker in lowered for marker in (
        "nel dettaglio", "approfond", "analizza", "analisi completa", "esaustiv",
        "non ho capito", "non mi e chiaro", "non mi è chiaro", "spieg",
        "come e stato risolto", "come è stato risolto", "quello che e accaduto",
        "quello che è accaduto", "cosa e successo", "cosa è successo",
    )):
        return "expanded"
    if route.intent == "project_summary" and not any(marker in lowered for marker in ("breve", "sintetico")):
        return "expanded"
    return "standard"


def infer_presentation(question: str, route: AssistantQueryRoute) -> str:
    lowered = compact_whitespace(question).lower()
    if route.intent in {"company_count", "team_count", "task_count"}:
        return "direct"
    if any(marker in lowered for marker in ("non ho capito", "non mi e chiaro", "non mi è chiaro", "spieg", "quello che e accaduto", "quello che è accaduto", "come e stato risolto", "come è stato risolto")):
        return "adaptive"
    if route.intent in {"company_list", "team_list", "task_list", "document_list", "open_alerts", "resolved_issues"}:
        return "list"
    if route.intent in {"activity_by_date", "timeline_summary"}:
        return "timeline"
    if route.intent == "document_search":
        return "document_evidence"
    if any(
        marker in lowered
        for marker in (
            "riferimento esatto",
            "codice esatto",
            "codice preciso",
            "qual e il codice",
            "qual è il codice",
            "quanti millimetri",
        )
    ):
        return "direct"
    return "adaptive"


def build_override_plan(response_mode: str) -> AssistantAnswerPlan | None:
    if response_mode == AssistantResponseMode.SINTESI:
        return AssistantAnswerPlan(
            target_length="long",
            response_structure="adaptive",
            citation_density="medium",
            answer_mode="operational_summary",
            answer_sections=[],
            reasoning=["response_mode_override:sintesi"],
            depth="expanded",
            presentation="adaptive",
        )
    if response_mode == AssistantResponseMode.TIMELINE:
        return AssistantAnswerPlan(
            target_length="medium",
            response_structure="timeline",
            citation_density="high",
            answer_mode="timeline",
            answer_sections=[],
            reasoning=["response_mode_override:timeline"],
            depth="standard",
            presentation="timeline",
        )
    if response_mode == AssistantResponseMode.CHECKLIST:
        return AssistantAnswerPlan(
            target_length="medium",
            response_structure="checklist",
            citation_density="medium",
            answer_mode="checklist",
            answer_sections=[],
            reasoning=["response_mode_override:checklist"],
            depth="standard",
            presentation="checklist",
        )
    if response_mode == AssistantResponseMode.DOCUMENTALE:
        return AssistantAnswerPlan(
            target_length="medium",
            response_structure="document_brief",
            citation_density="high",
            answer_mode="document_brief",
            answer_sections=[],
            reasoning=["response_mode_override:documentale"],
            depth="standard",
            presentation="document_evidence",
        )
    return None


def plan_assistant_answer(
    *,
    question: str,
    route: AssistantQueryRoute,
    response_mode: str = AssistantResponseMode.AUTO,
    has_conversation_context: bool = False,
) -> AssistantAnswerPlan:
    if needs_clarification(question, has_conversation_context=has_conversation_context):
        return AssistantAnswerPlan(
            target_length="short",
            response_structure="direct",
            citation_density="low",
            answer_mode="clarification",
            reasoning=["answerability:needs_clarification", "unresolved_reference"],
            answerability="needs_clarification",
            depth="compact",
            presentation="clarification",
            requirements=[
                "Ask one concise clarification question.",
                "Do not infer or answer the unresolved project fact.",
            ],
        )

    override = build_override_plan(response_mode)
    if override is not None:
        return override

    lowered = compact_whitespace(question).lower()
    asks_brevity = any(
        marker in lowered for marker in ("breve", "brevissimo", "in una riga", "in due righe", "sintetico")
    )
    asks_detail = any(marker in lowered for marker in ("dettaglio", "approfond", "spiega", "analizza"))
    reasoning: list[str] = [f"route:{route.intent}", f"strategy:{route.strategy}"]

    if route.intent in {"company_count", "team_count", "task_count", "document_list"}:
        target_length = "short" if not asks_detail else "medium"
        answer_sections = []
        answer_mode = "fact_list"
        citation_density = "low"
        response_structure = "direct" if not asks_detail else "brief"
    elif route.intent in {"company_list", "team_list", "task_list", "task_status", "open_alerts", "resolved_issues"}:
        target_length = "short" if asks_brevity else "medium"
        answer_sections = []
        answer_mode = "operational_list"
        citation_density = "medium"
        response_structure = "brief"
    elif route.intent in {"activity_by_date", "timeline_summary"}:
        target_length = "medium"
        answer_sections = []
        answer_mode = "timeline"
        citation_density = "high"
        response_structure = "timeline"
    elif route.intent in {"document_search"}:
        target_length = "medium" if asks_brevity else "long"
        answer_sections = []
        answer_mode = "document_brief"
        citation_density = "high"
        response_structure = "document_brief"
    elif route.intent in {"project_summary", "generic_semantic"}:
        target_length = "long" if not asks_brevity else "medium"
        answer_sections = []
        answer_mode = "operational_summary"
        citation_density = "medium"
        response_structure = "narrative" if asks_brevity else "deep_report"
    else:
        target_length = "medium"
        answer_sections = []
        answer_mode = "operational_summary"
        citation_density = "medium"
        response_structure = "narrative"

    if asks_brevity:
        reasoning.append("user_requested_brevity")
    if asks_detail:
        reasoning.append("user_requested_detail")
    reasoning.append(f"answer_shape:{response_structure}")

    return AssistantAnswerPlan(
        target_length=target_length,
        response_structure=response_structure,
        citation_density=citation_density,
        answer_mode=answer_mode,
        answer_sections=answer_sections,
        reasoning=reasoning,
        depth=infer_depth(question, route),
        presentation=infer_presentation(question, route),
        requirements=[
            "Answer every part of the user's request exactly once.",
            "Attach evidence to factual claims instead of listing unrelated retrieved sources.",
        ],
    )
