from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import re
import sys
from typing import Any

from django.conf import settings

from edilcloud.platform.test_center_actions import build_test_center_action_detail
from edilcloud.platform.test_center_run_ledger import load_action_run_from_path


SUPPORTED_OPERATIONS = {"rerun_quality_suite", "rerun_loadtest_suite"}
LOADTEST_PROFILES = {"auth-burst", "mixed-crud", "read-heavy"}


class TestCenterActionRunError(RuntimeError):
    pass


def _artifact_root() -> Path:
    configured = getattr(settings, "TEST_CENTER_ARTIFACT_DIR", "")
    if configured:
        return Path(str(configured)).resolve()
    return Path(getattr(settings, "BASE_DIR", ".")).resolve()


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-")[:80] or "run"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _quality_suite_for_action(action: dict[str, Any]) -> str:
    platform = str(action.get("platform") or "")
    target = action.get("target")
    if platform == "backend":
        return "backend"
    if platform == "frontend-next":
        return "frontend-next"
    if platform == "flutter" and target == "android":
        return "flutter-android"
    if platform == "flutter" and target == "ios":
        return "flutter-ios"
    if platform == "flutter":
        return "flutter"
    raise TestCenterActionRunError(f"Piattaforma quality non supportata: {platform}.")


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _build_quality_command(action: dict[str, Any]) -> tuple[list[str], str]:
    suite = _quality_suite_for_action(action)
    command = [
        sys.executable,
        "scripts/run_quality_suite.py",
        "--suite",
        suite,
        "--fail-on-threshold",
    ]
    return command, f"Preparata quality suite {suite} in dry-run controllato."


def _build_loadtest_command(
    *,
    profile: str,
    host: str,
    users: int,
    spawn_rate: float,
    run_time: str,
) -> tuple[list[str], str]:
    if profile not in LOADTEST_PROFILES:
        raise TestCenterActionRunError(f"Profilo Locust non supportato: {profile}.")
    safe_users = max(1, min(users, 250))
    safe_spawn_rate = max(0.1, min(spawn_rate, 100.0))
    safe_run_time = run_time.strip() or "2m"
    command = [
        sys.executable,
        "scripts/run_locust_suite.py",
        "--profile",
        profile,
        "--host",
        host.strip() or "http://localhost:3000",
        "--users",
        str(safe_users),
        "--spawn-rate",
        str(safe_spawn_rate),
        "--run-time",
        safe_run_time,
        "--fail-on-threshold",
    ]
    return command, f"Preparato Locust {profile} in dry-run controllato."


def _build_operation_plan(
    action: dict[str, Any],
    *,
    operation: str,
    loadtest_profile: str,
    loadtest_host: str,
    loadtest_users: int,
    loadtest_spawn_rate: float,
    loadtest_run_time: str,
) -> tuple[list[str], str]:
    if operation == "rerun_quality_suite":
        return _build_quality_command(action)
    if operation == "rerun_loadtest_suite":
        return _build_loadtest_command(
            profile=loadtest_profile,
            host=loadtest_host,
            users=loadtest_users,
            spawn_rate=loadtest_spawn_rate,
            run_time=loadtest_run_time,
        )
    raise TestCenterActionRunError(f"Operazione non supportata: {operation}.")


def _validate_action(action: dict[str, Any], *, action_id: str, operation: str) -> None:
    if operation not in SUPPORTED_OPERATIONS:
        raise TestCenterActionRunError(f"Operazione non supportata: {operation}.")
    allowed_operations = set(action.get("allowed_operations") or [])
    if operation not in allowed_operations:
        raise TestCenterActionRunError(
            f"Operazione {operation} non consentita per action {action_id}."
        )
    if action.get("state") == "blocked":
        raise TestCenterActionRunError(f"Action {action_id} bloccata.")


def _write_payload(action_id: str, operation: str, payload: dict[str, Any]) -> Path:
    root = _artifact_root()
    run_name = f"{_timestamp()}--{_slug(action_id)}--{_slug(operation)}--planned"
    run_dir = root / ".tmp" / "test-center" / "action-runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "action-run.json"
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return artifact_path


def prepare_action_run(
    *,
    action_id: str,
    operation: str,
    actor_id: str,
    actor_label: str,
    approved_by: str | None = None,
    note: str = "",
    loadtest_profile: str = "read-heavy",
    loadtest_host: str = "http://localhost:3000",
    loadtest_users: int = 10,
    loadtest_spawn_rate: float = 5.0,
    loadtest_run_time: str = "2m",
) -> dict[str, Any]:
    action = build_test_center_action_detail(action_id)
    if action is None:
        raise TestCenterActionRunError(f"Azione Test Center non trovata: {action_id}.")
    _validate_action(action, action_id=action_id, operation=operation)
    command, summary = _build_operation_plan(
        action,
        operation=operation,
        loadtest_profile=loadtest_profile,
        loadtest_host=loadtest_host,
        loadtest_users=loadtest_users,
        loadtest_spawn_rate=loadtest_spawn_rate,
        loadtest_run_time=loadtest_run_time,
    )

    source_issue = action.get("source_issue") if isinstance(action.get("source_issue"), dict) else {}
    audit = action.get("audit") if isinstance(action.get("audit"), dict) else {}
    evidence = [
        f"Action state: {action.get('state')}",
        f"Risk: {action.get('risk')}",
        "Preparazione generata da API Test Center.",
    ]
    if note.strip():
        evidence.append(f"Nota operatore: {note.strip()[:240]}")

    payload = {
        "status": "planned",
        "mode": "dry_run",
        "action_id": action_id,
        "issue_id": str(action.get("issue_id") or source_issue.get("id") or "") or None,
        "operation": operation,
        "platform": str(action.get("platform") or "unknown"),
        "target": action.get("target"),
        "category": str(action.get("category") or "unknown"),
        "generated_at": _utc_now(),
        "started_at": None,
        "finished_at": None,
        "duration_seconds": 0.0,
        "actor": {
            "kind": "superuser",
            "id": actor_id,
            "label": actor_label or actor_id,
        },
        "command": _command_text(command),
        "cwd": str(Path(getattr(settings, "BASE_DIR", ".")).resolve()),
        "returncode": None,
        "summary": summary,
        "stdout_tail": "",
        "stderr_tail": "",
        "artifacts": {},
        "evidence": evidence,
        "next_step": (
            "Eseguire l'operazione controllata solo dopo review delle evidenze e delle soglie."
        ),
        "audit": {
            "will_modify_code": False,
            "will_touch_production": False,
            "approval_required": bool(audit.get("requires_operator_approval", True)),
            "approved_by": approved_by or None,
        },
    }
    artifact_path = _write_payload(action_id, operation, payload)
    run = load_action_run_from_path(artifact_path)
    if run is None:
        raise TestCenterActionRunError("Run preparata ma artifact non leggibile.")
    return run
