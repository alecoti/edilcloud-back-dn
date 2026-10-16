"""Versioned application contracts, shared by preflight, writers and reviewers.

Storage keys remain compatible with existing documents. A policy describes
requirements and admissible evidence; an LLM cannot waive those requirements.
"""

from dataclasses import asdict, dataclass

POLICY_VERSION = "2026.10.16.v3.1"
ALIASES = {"inspection_report": "inspection", "coordination_minutes": "coordination"}
CANONICAL = {value: key for key, value in ALIASES.items()}
SOURCE_KINDS = (
    "project", "request", "declaration", "member", "post", "comment", "attachment",
    "image_attachment", "task", "activity", "photo", "document", "drawing", "drawing_pin",
    "event", "previous_elaborato",
)


def storage_type(value):
    return ALIASES.get(value, value) if isinstance(value, str) else value


@dataclass(frozen=True)
class DocumentTypePolicy:
    key: str
    storage_key: str
    required_fields: tuple[str, ...]
    forbidden_inferences: tuple[str, ...]
    critical_facts: tuple[str, ...]
    completion_rules: tuple[str, ...]
    required_event: str = ""
    allowed_sources: tuple[str, ...] = SOURCE_KINDS
    signature_rules: tuple[str, ...] = (
        "explicit_personal_consent", "revision_scoped", "never_infer_signature_or_attendance",
    )
    layout: str = "reference-20261015"
    version: str = POLICY_VERSION

    def snapshot(self, sections):
        return {
            **asdict(self),
            "required_sections": [s["key"] for s in sections if s.get("required")],
            "fast_path_rules": {
                "empty_requires_no_significant_evidence": True,
                "max_simple_records": 4,
                "max_simple_characters": 6000,
                "requires_complete_reading": True,
                "excludes_files_media_alerts_conditions_and_multiple_dates": True,
            },
            "deep_path_rules": {
                "max_standard_characters": 60000,
                "max_standard_records": 40,
                "max_standard_pages": 12,
                "max_standard_images": 8,
                "max_standard_days": 7,
                "unbounded_batched_processing": True,
            },
        }


POLICIES = {
    "daily_report": DocumentTypePolicy(
        "daily_report", "daily_report",
        ("report_date", "project", "recorded_activities", "companies", "attendance", "hours"),
        ("planned_is_executed", "membership_is_attendance", "no_records_is_site_closed"),
        ("activity", "decision", "outcome", "interruption", "weather"),
        ("same_day_only", "missing_values_are_editable", "no_silent_source_exclusions"),
    ),
    "inspection": DocumentTypePolicy(
        "inspection_report", "inspection",
        ("visit_date", "visit_declaration", "locations", "confirmed_participants", "findings"),
        ("request_is_visit", "author_is_attendee", "proposal_is_decision", "executed_is_verified"),
        ("visit", "finding", "decision", "request", "outcome", "condition"),
        ("visit_must_be_declared", "attendees_require_confirmation", "distinguish_fact_kinds"),
        required_event="visit",
    ),
    "coordination": DocumentTypePolicy(
        "coordination_minutes", "coordination",
        ("meeting_date", "meeting_declaration", "confirmed_participants", "topics", "decisions"),
        ("async_thread_is_meeting", "membership_is_attendance", "proposal_is_decision"),
        ("meeting", "decision", "request", "condition", "outcome"),
        ("meeting_must_be_declared", "decisions_require_attribution", "open_points_are_preserved"),
        required_event="meeting",
    ),
    "periodic_report": DocumentTypePolicy(
        "periodic_report", "periodic_report",
        ("period", "project", "documented_progress", "issue_evolution", "decisions"),
        ("current_progress_is_historical", "planned_is_executed", "assigned_is_closed"),
        ("activity", "decision", "outcome", "condition", "interruption"),
        ("whole_period_inventory", "preserve_evolution", "date_current_snapshots"),
    ),
    "photo_report": DocumentTypePolicy(
        "photo_report", "photo_report",
        ("period", "actual_photographs", "provenance", "photo_context", "photo_date", "captions"),
        ("image_implies_measurement", "image_implies_compliance", "image_implies_verified_completion",
         "upload_date_is_capture_date"),
        ("finding", "condition", "visual_limitation"),
        ("actual_images_required", "every_media_has_outcome", "captions_have_provenance"),
    ),
    "issue_report": DocumentTypePolicy(
        "issue_report", "issue_report",
        ("issue_identity", "chronology", "communications", "latest_outcome", "open_conditions"),
        ("executed_is_verified", "conditional_is_closed", "request_is_execution"),
        ("finding", "decision", "request", "outcome", "condition", "reopening"),
        ("thread_until_reference_end", "preserve_outcomes", "preserve_open_conditions"),
    ),
}


def policy_for(document_type):
    try:
        return POLICIES[storage_type(document_type)]
    except (KeyError, TypeError) as exc:
        raise ValueError("Tipo di elaborato non supportato.") from exc
