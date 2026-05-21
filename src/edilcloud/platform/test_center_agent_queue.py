from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from edilcloud.platform.test_center_actions import build_test_center_actions
from edilcloud.platform.test_center_issues import build_test_center_issues


AUTO_ALLOWED_OPERATIONS = {
    "rerun_quality_suite",
    "rerun_loadtest_suite",
    "refresh_runtime_budget",
}


def _generated_at() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _action_by_issue_id(actions_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    actions = actions_payload.get("actions", [])
    return {
        str(action.get("issue_id") or ""): action
        for action in actions
        if isinstance(action, dict) and action.get("issue_id")
    }


def _decision_state(
    issue: dict[str, Any],
    action: dict[str, Any] | None,
) -> tuple[str, str]:
    automation = issue.get("automation") if isinstance(issue.get("automation"), dict) else {}
    lifecycle = issue.get("lifecycle") if isinstance(issue.get("lifecycle"), dict) else {}
    if lifecycle.get("escalation_state") == "due":
        return (
            "escalation_due",
            "Issue oltre SLA: serve priorita operativa o assegnazione esplicita.",
        )
    if automation.get("state") == "blocked" or not action:
        return (
            "blocked",
            "Manca una action eseguibile o una sorgente dati stabile.",
        )
    if automation.get("state") == "manual_review_required":
        return (
            "human_review_required",
            "La correzione puo toccare comportamento o performance: serve lettura umana.",
        )
    allowed_operations = {
        str(operation)
        for operation in action.get("allowed_operations", [])
        if isinstance(operation, str)
    }
    if automation.get("state") == "candidate" and allowed_operations & AUTO_ALLOWED_OPERATIONS:
        return (
            "auto_dry_run_candidate",
            "Candidata per rilancio automatico in dry-run con guardrail attivi.",
        )
    return (
        "human_review_required",
        "Non ci sono ancora abbastanza garanzie per esecuzione autonoma.",
    )


def _next_operation(action: dict[str, Any] | None) -> str | None:
    if not action:
        return None
    for operation in action.get("allowed_operations", []):
        operation = str(operation)
        if operation in AUTO_ALLOWED_OPERATIONS:
            return operation
    return None


def _queue_item(issue: dict[str, Any], action: dict[str, Any] | None) -> dict[str, Any]:
    state, reason = _decision_state(issue, action)
    next_operation = _next_operation(action)
    can_auto_launch = state == "auto_dry_run_candidate" and next_operation is not None
    lifecycle = issue.get("lifecycle") if isinstance(issue.get("lifecycle"), dict) else {}
    return {
        "id": f"agent:{issue.get('id')}",
        "issue_id": issue.get("id"),
        "action_id": action.get("id") if action else None,
        "state": state,
        "platform": issue.get("platform"),
        "target": issue.get("target"),
        "category": issue.get("category"),
        "severity": issue.get("severity"),
        "title": issue.get("title"),
        "summary": issue.get("summary"),
        "reason": reason,
        "next_operation": next_operation,
        "can_auto_launch": can_auto_launch,
        "priority": _priority(issue, state),
        "lifecycle": lifecycle,
        "guardrails": {
            "mode": "dry_run",
            "will_modify_code": False,
            "will_touch_production": False,
            "requires_operator_approval": not can_auto_launch,
            "allowed_operations": action.get("allowed_operations", []) if action else [],
        },
        "verification": issue.get("verification"),
    }


def _priority(issue: dict[str, Any], state: str) -> int:
    severity_rank = {"critical": 90, "warning": 60, "info": 30}
    score = severity_rank.get(str(issue.get("severity") or "info"), 10)
    if state == "escalation_due":
        score += 30
    if state == "auto_dry_run_candidate":
        score += 10
    lifecycle = issue.get("lifecycle") if isinstance(issue.get("lifecycle"), dict) else {}
    age_hours = lifecycle.get("age_hours")
    if isinstance(age_hours, int | float):
        score += min(int(age_hours), 30)
    return score


def build_test_center_agent_queue() -> dict[str, Any]:
    issues_payload = build_test_center_issues()
    actions_payload = build_test_center_actions()
    actions_by_issue = _action_by_issue_id(actions_payload)
    items = [
        _queue_item(issue, actions_by_issue.get(str(issue.get("id") or "")))
        for issue in issues_payload.get("issues", [])
        if isinstance(issue, dict)
    ]
    items.sort(key=lambda item: int(item.get("priority") or 0), reverse=True)
    return {
        "generated_at": _generated_at(),
        "status": "ok" if not items else "attention",
        "mode": "dry_run_only",
        "summary": {
            "total": len(items),
            "auto_dry_run_candidates": sum(
                item["state"] == "auto_dry_run_candidate" for item in items
            ),
            "human_review_required": sum(
                item["state"] == "human_review_required" for item in items
            ),
            "blocked": sum(item["state"] == "blocked" for item in items),
            "escalations_due": sum(item["state"] == "escalation_due" for item in items),
        },
        "items": items,
    }
