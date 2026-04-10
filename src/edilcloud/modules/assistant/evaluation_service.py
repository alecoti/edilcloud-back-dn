from __future__ import annotations

from collections import Counter
import re
from typing import Any

from edilcloud.modules.assistant.query_router import AssistantQueryRoute


TOKEN_RE = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)


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


def evaluate_answer_against_sources(
    *,
    answer: str,
    citations: list[dict[str, Any]],
    route: AssistantQueryRoute,
) -> dict[str, Any]:
    normalized_answer = normalize_text(answer)
    combined_evidence = " ".join(
        normalize_text(str(citation.get("label") or "")) + " " + normalize_text(str(citation.get("snippet") or ""))
        for citation in citations[:8]
    )
    grounding_overlap = score_overlap(normalized_answer, combined_evidence)
    source_types = [str(citation.get("source_type") or "unknown") for citation in citations]
    expected_source_types = set(route.selected_source_types)
    topical_hits = sum(1 for source_type in source_types if source_type in expected_source_types)
    relevance_score = topical_hits / max(1, min(len(source_types), 4))
    coverage_score = min(len(citations), 4) / 4.0
    no_support = int(len(citations) == 0 or grounding_overlap < 0.08)
    mismatch = int(bool(source_types) and topical_hits == 0)
    evidence_counter = Counter(source_types)

    return {
        "source_relevance_score": round(relevance_score, 3),
        "answer_grounding_score": round(grounding_overlap, 3),
        "answer_source_coverage": round(coverage_score, 3),
        "mismatch_rate": float(mismatch),
        "hallucination_risk": "high" if no_support else ("medium" if grounding_overlap < 0.18 else "low"),
        "unsupported_answer": bool(no_support),
        "topical_source_match": bool(topical_hits),
        "source_type_histogram": dict(evidence_counter),
    }
