from __future__ import annotations

from collections import Counter
import math
import re
from typing import Any

from edilcloud.modules.assistant.query_router import AssistantQueryRoute


TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
RANKING_EVAL_KS = (1, 3, 5)
SUPPORT_WEAK_THRESHOLD = 0.08
SUPPORT_STRONG_THRESHOLD = 0.18
NOISY_CONTEXT_THRESHOLD = 0.03
METADATA_ONLY_SOURCE_TYPES = {
    "documents_catalog",
    "open_alerts_summary",
    "project",
    "resolved_issues_summary",
    "team_directory",
}
SUPPORT_METADATA_KEYS = (
    "activity_title",
    "assigned_company",
    "company_name",
    "file_name",
    "folder_name",
    "issue_status",
    "page_reference",
    "section_reference",
    "task_name",
)


def normalize_text(value: str | None) -> str:
    return (value or "").strip()


def tokenize(value: str | None) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(normalize_text(value))]


def score_overlap(answer: str, evidence: str) -> float:
    answer_tokens = set(tokenize(answer))
    evidence_tokens = set(tokenize(evidence))
    if not answer_tokens or not evidence_tokens:
        return 0.0
    return len(answer_tokens & evidence_tokens) / max(1, len(answer_tokens))


def normalize_metadata_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float, str)):
        return normalize_text(str(value))
    if isinstance(value, list):
        return " ".join(filter(None, (normalize_metadata_value(item) for item in value)))
    if isinstance(value, dict):
        return " ".join(filter(None, (normalize_metadata_value(item) for item in value.values())))
    if hasattr(value, "isoformat"):
        return normalize_text(str(value.isoformat()))
    return normalize_text(str(value))


def citation_evidence_text(citation: dict[str, Any], *, include_metadata: bool = True) -> str:
    parts = [
        normalize_text(str(citation.get("label") or "")),
        normalize_text(str(citation.get("snippet") or "")),
    ]
    metadata = citation.get("metadata") if isinstance(citation.get("metadata"), dict) else {}
    if include_metadata:
        parts.extend(normalize_metadata_value(metadata.get(key)) for key in SUPPORT_METADATA_KEYS)
    return " ".join(part for part in parts if part)


def score_citation_support(answer: str, citation: dict[str, Any]) -> float:
    visible_score = score_overlap(answer, citation_evidence_text(citation, include_metadata=False))
    metadata_score = score_overlap(answer, citation_evidence_text(citation, include_metadata=True))
    # Metadata is useful for routing and disambiguation, but it should not make a
    # weak textual citation look like a fully read document.
    return max(visible_score, min(metadata_score, visible_score + 0.05))


def source_support_level(*, best_score: float, grounding_overlap: float, citations_count: int) -> str:
    if citations_count <= 0:
        return "none"
    if best_score >= SUPPORT_STRONG_THRESHOLD or grounding_overlap >= SUPPORT_STRONG_THRESHOLD:
        return "strong"
    if best_score >= SUPPORT_WEAK_THRESHOLD or grounding_overlap >= SUPPORT_WEAK_THRESHOLD:
        return "medium"
    return "weak"


def citation_source_type(citation: dict[str, Any]) -> str:
    return normalize_text(str(citation.get("source_type") or "unknown"))


def citation_relevance_grade(
    citation: dict[str, Any],
    *,
    expected_source_types: set[str],
    seen_source_types: set[str],
) -> int:
    source_type = citation_source_type(citation)
    if source_type not in expected_source_types:
        return 0
    # First hits for a useful source type are more valuable than repeated hits
    # because they prove coverage across the expected evidence surface.
    if source_type in seen_source_types:
        return 1
    seen_source_types.add(source_type)
    return 2


def discounted_cumulative_gain(grades: list[int]) -> float:
    score = 0.0
    for index, grade in enumerate(grades, start=1):
        if grade <= 0:
            continue
        score += (2**grade - 1) / (1 if index == 1 else math.log2(index + 1))
    return score


def evaluate_retrieval_ranking(
    *,
    citations: list[dict[str, Any]],
    route: AssistantQueryRoute,
) -> dict[str, Any]:
    expected_source_types = {
        normalize_text(str(source_type))
        for source_type in list(route.selected_source_types or [])
        if normalize_text(str(source_type))
    }
    source_types = [citation_source_type(citation) for citation in citations]
    if not expected_source_types:
        return {
            "retrieval_expected_source_type_count": 0,
            "retrieval_relevant_source_type_count": 0,
            "retrieval_mrr": 0.0,
            "retrieval_ranking_weak": False,
        }

    seen_for_grade: set[str] = set()
    grades = [
        citation_relevance_grade(
            citation,
            expected_source_types=expected_source_types,
            seen_source_types=seen_for_grade,
        )
        for citation in citations
    ]
    relevant_positions = [
        index
        for index, source_type in enumerate(source_types, start=1)
        if source_type in expected_source_types
    ]
    distinct_relevant = {source_type for source_type in source_types if source_type in expected_source_types}
    metrics: dict[str, Any] = {
        "retrieval_expected_source_types": sorted(expected_source_types),
        "retrieval_expected_source_type_count": len(expected_source_types),
        "retrieval_relevant_source_type_count": len(distinct_relevant),
        "retrieval_mrr": round(1.0 / relevant_positions[0], 3) if relevant_positions else 0.0,
    }

    for k in RANKING_EVAL_KS:
        top_source_types = source_types[:k]
        distinct_top_relevant = {
            source_type for source_type in top_source_types if source_type in expected_source_types
        }
        recall = len(distinct_top_relevant) / max(1, len(expected_source_types))
        precision = sum(1 for source_type in top_source_types if source_type in expected_source_types) / max(1, k)
        top_grades = grades[:k]
        ideal_relevant_count = min(len(expected_source_types), k)
        ideal_grades = [2 for _index in range(ideal_relevant_count)]
        dcg = discounted_cumulative_gain(top_grades)
        ideal_dcg = discounted_cumulative_gain(ideal_grades)
        metrics[f"retrieval_recall_at_{k}"] = round(recall, 3)
        metrics[f"retrieval_precision_at_{k}"] = round(precision, 3)
        metrics[f"retrieval_ndcg_at_{k}"] = round(min(dcg / max(ideal_dcg, 0.0001), 1.0), 3)

    metrics["retrieval_ranking_weak"] = bool(
        metrics.get("retrieval_mrr", 0.0) == 0.0
        or (
            metrics.get("retrieval_recall_at_5", 0.0) < 0.2
            and metrics.get("retrieval_ndcg_at_5", 0.0) < 0.45
        )
    )
    return metrics


def evaluate_answer_against_sources(
    *,
    answer: str,
    citations: list[dict[str, Any]],
    route: AssistantQueryRoute,
) -> dict[str, Any]:
    normalized_answer = normalize_text(answer)
    inspected_citations = citations[:8]
    combined_evidence = " ".join(citation_evidence_text(citation) for citation in inspected_citations)
    grounding_overlap = score_overlap(normalized_answer, combined_evidence)
    source_types = [str(citation.get("source_type") or "unknown") for citation in citations]
    expected_source_types = set(route.selected_source_types)
    topical_hits = sum(1 for source_type in source_types if source_type in expected_source_types)
    relevance_score = topical_hits / max(1, min(len(source_types), 4))
    coverage_score = min(len(citations), 4) / 4.0
    mismatch = int(bool(source_types) and topical_hits == 0)
    evidence_counter = Counter(source_types)
    ranking_metrics = evaluate_retrieval_ranking(citations=citations, route=route)
    citation_supports = [
        {
            "source_key": str(citation.get("source_key") or ""),
            "source_type": str(citation.get("source_type") or "unknown"),
            "support_score": round(score_citation_support(normalized_answer, citation), 3),
            "topical_match": str(citation.get("source_type") or "unknown") in expected_source_types,
            "metadata_only": str(citation.get("source_type") or "unknown") in METADATA_ONLY_SOURCE_TYPES,
        }
        for citation in inspected_citations
    ]
    support_scores = [float(item["support_score"]) for item in citation_supports]
    strong_source_count = sum(1 for score in support_scores if score >= SUPPORT_STRONG_THRESHOLD)
    weak_source_count = sum(1 for score in support_scores if score < SUPPORT_WEAK_THRESHOLD)
    noisy_source_count = sum(
        1
        for item in citation_supports
        if float(item["support_score"]) < NOISY_CONTEXT_THRESHOLD and not bool(item["topical_match"])
    )
    metadata_only_source_count = sum(1 for item in citation_supports if bool(item["metadata_only"]))
    citation_support_rate = sum(1 for score in support_scores if score >= SUPPORT_WEAK_THRESHOLD) / max(
        1,
        len(support_scores),
    )
    noisy_context_rate = noisy_source_count / max(1, len(support_scores))
    best_source_score = max(support_scores, default=0.0)
    avg_source_score = sum(support_scores) / max(1, len(support_scores))
    support_level = source_support_level(
        best_score=best_source_score,
        grounding_overlap=grounding_overlap,
        citations_count=len(citations),
    )
    no_support = int(len(citations) == 0 or support_level in {"none", "weak"})
    weak_evidence = support_level in {"none", "weak"}
    hallucination_risk = (
        "high"
        if no_support
        else ("medium" if support_level == "medium" or noisy_context_rate > 0.5 else "low")
    )

    return {
        "source_relevance_score": round(relevance_score, 3),
        "answer_grounding_score": round(grounding_overlap, 3),
        "answer_source_coverage": round(coverage_score, 3),
        "citation_support_rate": round(citation_support_rate, 3),
        "avg_source_support_score": round(avg_source_score, 3),
        "best_source_support_score": round(best_source_score, 3),
        "source_support_level": support_level,
        "strong_source_count": strong_source_count,
        "weak_source_count": weak_source_count,
        "metadata_only_source_count": metadata_only_source_count,
        "noisy_context_rate": round(noisy_context_rate, 3),
        "noisy_source_count": noisy_source_count,
        "mismatch_rate": float(mismatch),
        "hallucination_risk": hallucination_risk,
        "unsupported_answer": bool(no_support),
        "weak_evidence": weak_evidence,
        "topical_source_match": bool(topical_hits),
        "source_type_histogram": dict(evidence_counter),
        "citation_supports": citation_supports,
        **ranking_metrics,
    }
