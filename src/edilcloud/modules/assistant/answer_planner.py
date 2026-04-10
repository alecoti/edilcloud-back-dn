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


def build_override_plan(response_mode: str) -> AssistantAnswerPlan | None:
    if response_mode == AssistantResponseMode.SINTESI:
        return AssistantAnswerPlan(
            target_length="long",
            response_structure="sectioned",
            citation_density="medium",
            answer_mode="operational_summary",
            answer_sections=[
                "Sintesi operativa",
                "Evidenze rilevanti",
                "Criticita aperte",
                "Prossimi passi",
            ],
            reasoning=["response_mode_override:sintesi"],
        )
    if response_mode == AssistantResponseMode.TIMELINE:
        return AssistantAnswerPlan(
            target_length="medium",
            response_structure="timeline",
            citation_density="high",
            answer_mode="timeline",
            answer_sections=["Timeline", "Impatti", "Prossimi passi"],
            reasoning=["response_mode_override:timeline"],
        )
    if response_mode == AssistantResponseMode.CHECKLIST:
        return AssistantAnswerPlan(
            target_length="medium",
            response_structure="checklist",
            citation_density="medium",
            answer_mode="checklist",
            answer_sections=["Checklist operativa", "Bloccanti", "Azioni successive"],
            reasoning=["response_mode_override:checklist"],
        )
    if response_mode == AssistantResponseMode.DOCUMENTALE:
        return AssistantAnswerPlan(
            target_length="medium",
            response_structure="document_brief",
            citation_density="high",
            answer_mode="document_brief",
            answer_sections=["Risposta breve", "Documenti rilevanti", "Dettagli trovati", "Cosa manca"],
            reasoning=["response_mode_override:documentale"],
        )
    return None


def plan_assistant_answer(
    *,
    question: str,
    route: AssistantQueryRoute,
    response_mode: str = AssistantResponseMode.AUTO,
) -> AssistantAnswerPlan:
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
        answer_sections = ["Risposta breve", "Perimetro"]
        answer_mode = "fact_list"
        citation_density = "low"
        response_structure = "compact"
    elif route.intent in {"company_list", "team_list", "task_list", "task_status", "open_alerts", "resolved_issues"}:
        target_length = "short" if asks_brevity else "medium"
        answer_sections = ["Risposta breve", "Dettagli essenziali", "Note di perimetro"]
        answer_mode = "operational_list"
        citation_density = "medium"
        response_structure = "sectioned"
    elif route.intent in {"activity_by_date", "timeline_summary"}:
        target_length = "medium"
        answer_sections = ["Timeline", "Impatti", "Punti da verificare"]
        answer_mode = "timeline"
        citation_density = "high"
        response_structure = "timeline"
    elif route.intent in {"document_search"}:
        target_length = "medium" if asks_brevity else "long"
        answer_sections = ["Risposta breve", "Documenti trovati", "Dettagli trovati", "Cosa manca"]
        answer_mode = "document_brief"
        citation_density = "high"
        response_structure = "document_brief"
    elif route.intent in {"project_summary", "generic_semantic"}:
        target_length = "long" if not asks_brevity else "medium"
        answer_sections = ["Sintesi operativa", "Evidenze rilevanti", "Criticita aperte", "Prossimi passi"]
        answer_mode = "operational_summary"
        citation_density = "medium"
        response_structure = "sectioned"
    else:
        target_length = "medium"
        answer_sections = ["Sintesi", "Evidenze", "Prossimi passi"]
        answer_mode = "operational_summary"
        citation_density = "medium"
        response_structure = "sectioned"

    if asks_brevity:
        reasoning.append("user_requested_brevity")
    if asks_detail:
        reasoning.append("user_requested_detail")

    return AssistantAnswerPlan(
        target_length=target_length,
        response_structure=response_structure,
        citation_density=citation_density,
        answer_mode=answer_mode,
        answer_sections=answer_sections,
        reasoning=reasoning,
    )
