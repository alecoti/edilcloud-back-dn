from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings

from edilcloud.platform.test_center_agent_queue import build_test_center_agent_queue
from edilcloud.platform.test_center_run_ledger import load_action_run_history


SUPPORTED_AGENT_OPERATIONS = {"rerun_quality_suite", "rerun_loadtest_suite"}
DEFAULT_MAX_TOTAL = 3
DEFAULT_MAX_PER_PLATFORM = 1
DEFAULT_MAX_PER_CATEGORY = 2
DEFAULT_COOLDOWN_HOURS = 1.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _utc_now_text() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _artifact_root() -> Path:
    configured = getattr(settings, "TEST_CENTER_ARTIFACT_DIR", "")
    if configured:
        return Path(str(configured)).resolve()
    return Path(getattr(settings, "BASE_DIR", ".")).resolve()


def _recent_runs_by_issue_id() -> dict[str, dict[str, Any]]:
    runs = load_action_run_history(limit=200).get("runs", [])
    latest: dict[str, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict):
            continue
        issue_id = str(run.get("issue_id") or "")
        if issue_id and issue_id not in latest:
            latest[issue_id] = run
    return latest


def _cooldown_reason(
    item: dict[str, Any],
    latest_runs: dict[str, dict[str, Any]],
    *,
    now: datetime,
    cooldown_hours: float,
) -> str | None:
    issue_id = str(item.get("issue_id") or "")
    latest = latest_runs.get(issue_id)
    if not latest:
        return None
    timestamp = _parse_timestamp(latest.get("finished_at") or latest.get("generated_at"))
    if timestamp is None:
        return None
    age_hours = (now - timestamp).total_seconds() / 3600
    if age_hours < cooldown_hours:
        return (
            "Cooldown attivo: ultima run {status} da {age:.2f}h.".format(
                status=latest.get("status") or "unknown",
                age=age_hours,
            )
        )
    return None


def _candidate_decision(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "queue_item_id": item.get("id"),
        "issue_id": item.get("issue_id"),
        "action_id": item.get("action_id"),
        "state": "selected",
        "operation": item.get("next_operation"),
        "platform": item.get("platform"),
        "target": item.get("target"),
        "category": item.get("category"),
        "priority": item.get("priority"),
        "reason": "Selezionata dal ciclo agentico in dry-run controllato.",
        "guardrails": item.get("guardrails"),
    }


def _skipped_decision(item: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "queue_item_id": item.get("id"),
        "issue_id": item.get("issue_id"),
        "action_id": item.get("action_id"),
        "state": "skipped",
        "operation": item.get("next_operation"),
        "platform": item.get("platform"),
        "target": item.get("target"),
        "category": item.get("category"),
        "priority": item.get("priority"),
        "reason": reason,
        "guardrails": item.get("guardrails"),
    }


def build_test_center_agent_cycle_plan(
    *,
    max_total: int = DEFAULT_MAX_TOTAL,
    max_per_platform: int = DEFAULT_MAX_PER_PLATFORM,
    max_per_category: int = DEFAULT_MAX_PER_CATEGORY,
    cooldown_hours: float = DEFAULT_COOLDOWN_HOURS,
) -> dict[str, Any]:
    queue = build_test_center_agent_queue()
    now = _utc_now()
    latest_runs = _recent_runs_by_issue_id()
    total_limit = max(0, min(max_total, 20))
    platform_limit = max(1, min(max_per_platform, 10))
    category_limit = max(1, min(max_per_category, 10))
    cooldown = max(0.0, min(cooldown_hours, 168.0))
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    platform_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}

    for item in queue.get("items", []):
        if not isinstance(item, dict):
            continue
        if item.get("state") != "auto_dry_run_candidate":
            skipped.append(_skipped_decision(item, reason="Non candidata a dry-run automatico."))
            continue
        operation = str(item.get("next_operation") or "")
        if operation not in SUPPORTED_AGENT_OPERATIONS:
            skipped.append(_skipped_decision(item, reason="Operazione non supportata dal runner agentico."))
            continue
        cooldown_reason = _cooldown_reason(
            item,
            latest_runs,
            now=now,
            cooldown_hours=cooldown,
        )
        if cooldown_reason:
            skipped.append(_skipped_decision(item, reason=cooldown_reason))
            continue
        platform = str(item.get("platform") or "unknown")
        category = str(item.get("category") or "unknown")
        if len(selected) >= total_limit:
            skipped.append(_skipped_decision(item, reason="Limite totale ciclo raggiunto."))
            continue
        if platform_counts.get(platform, 0) >= platform_limit:
            skipped.append(_skipped_decision(item, reason="Limite per piattaforma raggiunto."))
            continue
        if category_counts.get(category, 0) >= category_limit:
            skipped.append(_skipped_decision(item, reason="Limite per categoria raggiunto."))
            continue
        selected.append(_candidate_decision(item))
        platform_counts[platform] = platform_counts.get(platform, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1

    return {
        "generated_at": _utc_now_text(),
        "status": "ready" if selected else "idle",
        "mode": "plan_only",
        "limits": {
            "max_total": total_limit,
            "max_per_platform": platform_limit,
            "max_per_category": category_limit,
            "cooldown_hours": cooldown,
        },
        "summary": {
            "selected": len(selected),
            "skipped": len(skipped),
            "queue_total": queue.get("summary", {}).get("total", 0),
            "auto_dry_run_candidates": queue.get("summary", {}).get(
                "auto_dry_run_candidates",
                0,
            ),
        },
        "selected": selected,
        "skipped": skipped,
    }


def record_agent_cycle_plan(plan: dict[str, Any]) -> Path | None:
    root = _artifact_root()
    generated_at = str(plan.get("generated_at") or _utc_now_text())
    signature = hashlib.sha256(
        json.dumps(plan, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    timestamp = (
        generated_at.replace(":", "")
        .replace("-", "")
        .replace("T", "-")
        .replace("Z", "")
    )
    path = (
        root
        / ".tmp"
        / "test-center"
        / "agent-cycles"
        / f"{timestamp}--{signature}"
        / "agent-cycle-plan.json"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    except OSError:
        return None
    return path
