"""Deterministic routing: resource limits partition work, never drop sources."""

from collections import Counter
from dataclasses import asdict, dataclass
from enum import StrEnum
import re

from .models import DocumentEvidenceItem
from .policies import policy_for


class DocumentPath(StrEnum):
    FAST_0 = "FAST_0"
    FAST_1 = "FAST_1"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


@dataclass(frozen=True)
class DocumentPreflight:
    path: DocumentPath
    reason: str
    counts: dict
    significant_sources: int
    text_characters: int
    days: int
    policy_version: str

    def as_dict(self):
        return asdict(self)

    @classmethod
    def inspect(cls, job):
        job.refresh_from_db(fields=("workflow_state",))
        if not job.workflow_state.get("inventory_complete"):
            raise ValueError("Completa l'inventario prima di scegliere il percorso documentale.")
        document = job.revision.elaborato
        policy = policy_for(document.document_type)
        kinds = Counter()
        significant = characters = files = images = 0
        complex_content = False
        dates = set()
        problem_states = 0
        roots = DocumentEvidenceItem.objects.filter(job=job, parent_source_id="")
        for item in roots.iterator(chunk_size=100):
            kinds[item.kind] += 1
            if item.state == "excluded":
                if not item.reason:
                    raise ValueError("Una fonte esclusa deve avere una motivazione.")
                continue
            problem_states += item.state in {"unreadable", "failed"}
            data = item.payload.get("data", {})
            text = "\n".join(str(data.get(k) or "") for k in ("text", "context", "description", "note"))
            characters += len(text)
            file = bool(item.payload.get("file_ref"))
            files += file
            images += data.get("media_kind") == "image"
            operational = (
                item.kind in {"post", "comment", "declaration"} and bool(text.strip())
            ) or file or (
                item.kind == "event" and data.get("type") not in {
                    "post.created", "comment.created", "document.created", "project.created",
                }
            )
            significant += bool(operational)
            if operational:
                complex_content |= bool(
                    data.get("alert") or data.get("outside_period_context")
                    or re.search(
                        r"\b(condizion\w*|purch[eé]|salvo|contradd\w*|riapert\w*|non conform\w*|"
                        r"a patto|fino a\w*|in attesa|sospend\w*|sospens\w*|revoc\w*|rettific\w*|sment\w*|"
                        r"subject to|unless|until|pending|provided that|reopen\w*|contradict\w*)\b",
                        text, re.IGNORECASE,
                    )
                )
                dates.update(re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{4}\b", text))
        days = (document.period_end - document.period_start).days + 1
        if significant == 0:
            path, reason = DocumentPath.FAST_0, "no_significant_documentary_evidence"
        elif (
            days > 7 or significant > 40 or characters > 60000 or files > 4 or images > 8
            or problem_states or (document.document_type == "issue_report" and complex_content)
        ):
            path, reason = DocumentPath.DEEP, "partitioned_reading_and_independent_reviews_required"
        elif (
            significant <= 4 and characters <= 6000 and not files and not complex_content
            and days == 1 and len(dates) <= 1 and not policy.required_event
            and document.document_type != "issue_report"
        ):
            path, reason = DocumentPath.FAST_1, "small_complete_simple_text_scope"
        else:
            path, reason = DocumentPath.STANDARD, "ordinary_documentary_scope"
        return cls(path, reason, dict(kinds), significant, characters, days, policy.version)


def fast_review_reason(facts, quality):
    """Post-extraction guard: a cheap-looking input can reveal a complex case."""
    if quality.get("literal_quote_selection"):
        return "quote_selection_requires_independent_review"
    if len(facts) > 6:
        return "extracted_facts_exceed_simple_scope"
    sensitive = {"decision", "condition", "outcome", "reopening", "interruption", "visit", "meeting"}
    if any(f.nature in {"contradicted", "open"} or f.category in sensitive for f in facts):
        return "critical_or_stateful_facts_require_independent_review"
    if len({f.event_date for f in facts if f.event_date}) > 1:
        return "multiple_event_dates_require_independent_review"
    if any(issue["severity"] == "blocking" for issue in quality["issues"]):
        return "application_validation_requires_independent_review"
    return ""
