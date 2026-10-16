"""Typed documentary contracts: source -> fact -> requirement -> final block."""

from typing import Literal
import json
from pydantic import Field

from .content import Composition, StrictModel


class SourceReference(StrictModel):
    source_id: str
    # IDs of a page/text part, when the original record is larger than a batch.
    part_id: str
    page: int | None
    quote: str = Field(min_length=1)


class DocumentaryFact(StrictModel):
    id: str
    text: str = Field(min_length=1)
    nature: Literal["observed", "declared", "proposed", "decided", "executed", "verified",
                    "contradicted", "open"]
    category: Literal["activity", "finding", "decision", "proposal", "request", "outcome",
                      "condition", "reopening", "interruption", "weather", "visit", "meeting",
                      "person", "date", "visual_limitation", "other"]
    event_date: str
    author: str
    references: list[SourceReference] = Field(min_length=1)
    critical: bool
    relevant: bool
    relevance_reason: str


class SourceDisposition(StrictModel):
    part_id: str
    status: Literal["read", "excluded", "unreadable", "failed"]
    reason: str = Field(min_length=1)


class ReaderResult(StrictModel):
    facts: list[DocumentaryFact]
    sources: list[SourceDisposition]


class FactReconciliation(StrictModel):
    fact_id: str
    canonical_fact_id: str
    relevant: bool
    reason: str
    conflicts_with: list[str]
    related_fact_ids: list[str] = Field(default_factory=list)


class ReconciliationResult(StrictModel):
    facts: list[FactReconciliation]


class FactAllocation(StrictModel):
    fact_id: str
    section_key: str
    included: bool
    reason: str
    subsection_path: list[str] = Field(default_factory=list)


class RequirementDisposition(StrictModel):
    requirement_id: str
    status: Literal["satisfied", "missing", "requires_confirmation", "not_applicable"]
    fact_ids: list[str]
    reason: str


class DocumentPlan(StrictModel):
    allocations: list[FactAllocation]
    requirements: list[RequirementDisposition]


class ClaimReview(StrictModel):
    claim_id: str
    status: Literal["supported", "partially_supported", "contradicted", "not_verifiable"]
    represented_fact_ids: list[str]
    explanation: str


class FactualReview(StrictModel):
    claims: list[ClaimReview]


class CompletenessIssue(StrictModel):
    kind: Literal["unrepresented_fact", "missing_requirement", "unread_source", "missing_outcome",
                  "questionable_exclusion"]
    subject_id: str
    critical: bool
    explanation: str


class CompletenessReview(StrictModel):
    reviewed_source_ids: list[str]
    issues: list[CompletenessIssue]


class ImageDescription(StrictModel):
    description: str
    limitations: str
    is_document: bool


class FastDocumentResult(StrictModel):
    reading: ReaderResult
    composition: Composition
    plan: DocumentPlan


class StandardAnalysisResult(StrictModel):
    reading: ReaderResult
    plan: DocumentPlan


def validate_reader(result, parts):
    """A referenced source must be present and the quoted passage must exist."""
    def normalize(value):
        return " ".join(value.split())

    by_id = {p["part_id"]: p for p in parts}
    dispositions = [s.part_id for s in result.sources]
    if len(dispositions) != len(set(dispositions)) or set(dispositions) != set(by_id):
        raise ValueError("Ogni porzione di fonte deve avere un esito esplicito.")
    fact_ids = [f.id for f in result.facts]
    if len(fact_ids) != len(set(fact_ids)):
        raise ValueError("Identificatori di fatto duplicati nella lettura.")
    for fact in result.facts:
        if not fact.relevance_reason.strip():
            raise ValueError("La pertinenza del fatto deve essere motivata.")
        validated_references = []
        for ref in fact.references:
            part = by_id.get(ref.part_id)
            if not part or ref.source_id != part["source_id"] or ref.page != part.get("page"):
                raise ValueError("Il riferimento non corrisponde alla fonte esaminata.")
            if normalize(ref.quote) not in normalize(part["text"]):
                # A reader may cite two exact metadata fields while omitting
                # an intervening empty field. Preserve both literal passages
                # independently, never accept a fabricated contiguous quote.
                if part.get("origin_kind") not in {"project", "request", "member", "task", "activity"}:
                    raise ValueError("Il passaggio citato non è presente nella fonte originale.")
                try:
                    original = json.loads(part["text"])
                    selected = json.loads("{" + ref.quote.strip().strip("{}").strip() + "}")
                    fragments = [json.dumps({key: value}, ensure_ascii=False, separators=(",", ":"))[1:-1]
                                 for key, value in selected.items()]
                    if not selected or any(key not in original or type(original[key]) is not type(value)
                                           or original[key] != value for key, value in selected.items()):
                        raise ValueError
                    if any(fragment not in part["text"] for fragment in fragments):
                        raise ValueError
                except (ValueError, TypeError, AttributeError):
                    raise ValueError("Il passaggio citato non è presente nella fonte originale.") from None
                validated_references.extend(ref.model_copy(update={"quote": fragment}) for fragment in fragments)
            else:
                validated_references.append(ref)
        fact.references = validated_references
    return result


def enforce_fact_policy(facts, parts, policy):
    by_id = {p["part_id"]: p for p in parts}
    for fact in facts:
        origins = {by_id[r.part_id].get("origin_kind") for r in fact.references}
        if fact.category in policy.critical_facts:
            fact.critical = True
        if fact.critical:
            fact.relevant = True
        if origins <= {"member", "task", "activity", "project", "request"} and (
            fact.nature in {"executed", "verified"} or fact.category in {"visit", "meeting"}
        ):
            raise ValueError("Metadati, appartenenza al team e pianificazione non attestano eventi o esecuzioni.")
        if origins <= {"photo", "image_attachment"} and fact.nature in {"executed", "verified"}:
            raise ValueError("La sola analisi visiva non attesta completamento tecnico o verifica.")
    return facts
