from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings


ACTION_RUN_ARTIFACT_GLOBS = (
    ".tmp/test-center/action-runs/**/*.json",
    "docs/performance-history/action-runs/**/*.json",
)


def _artifact_root() -> Path:
    configured = getattr(settings, "TEST_CENTER_ARTIFACT_DIR", "")
    if configured:
        return Path(str(configured)).resolve()
    return Path(getattr(settings, "BASE_DIR", ".")).resolve()


def _candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ACTION_RUN_ARTIFACT_GLOBS:
        files.extend(path for path in root.glob(pattern) if path.is_file())
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _source_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _run_id(source_path: str) -> str:
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any, *, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:limit] if isinstance(item, str)]


def _compact_artifacts(payload: dict[str, Any]) -> dict[str, str]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in artifacts.items()
        if isinstance(value, str) and value
    }


def _run_status(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("status") or "").lower()
    if explicit in {"planned", "running", "pass", "fail", "blocked", "cancelled", "skipped"}:
        return explicit
    returncode = payload.get("returncode")
    if returncode is None:
        return "planned"
    return "pass" if int(returncode) == 0 else "fail"


def _normalize_action_run(
    root: Path,
    path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    source_path = _source_path(root, path)
    actor = _dict_or_empty(payload.get("actor"))
    audit = _dict_or_empty(payload.get("audit"))
    return {
        "id": _run_id(source_path),
        "status": _run_status(payload),
        "mode": str(payload.get("mode") or "dry_run"),
        "action_id": str(payload.get("action_id") or ""),
        "issue_id": payload.get("issue_id"),
        "operation": str(payload.get("operation") or "unknown"),
        "platform": str(payload.get("platform") or "unknown"),
        "target": payload.get("target"),
        "category": str(payload.get("category") or "unknown"),
        "generated_at": payload.get("generated_at"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "duration_seconds": float(payload.get("duration_seconds") or 0.0),
        "actor": {
            "kind": str(actor.get("kind") or "system"),
            "id": str(actor.get("id") or ""),
            "label": str(actor.get("label") or actor.get("id") or "system"),
        },
        "command": str(payload.get("command") or ""),
        "cwd": str(payload.get("cwd") or ""),
        "returncode": payload.get("returncode"),
        "summary": str(payload.get("summary") or ""),
        "stdout_tail": str(payload.get("stdout_tail") or "")[-4000:],
        "stderr_tail": str(payload.get("stderr_tail") or "")[-4000:],
        "artifacts": _compact_artifacts(payload),
        "source_path": source_path,
        "evidence": _string_list(payload.get("evidence"), limit=10),
        "next_step": str(payload.get("next_step") or ""),
        "audit": {
            "will_modify_code": bool(audit.get("will_modify_code", False)),
            "will_touch_production": bool(audit.get("will_touch_production", False)),
            "approved_by": audit.get("approved_by"),
            "approval_required": bool(audit.get("approval_required", True)),
        },
    }


def _matches_filters(
    run: dict[str, Any],
    *,
    action_id: str | None,
    status: str | None,
) -> bool:
    if action_id and str(run.get("action_id") or "") != action_id:
        return False
    if status and str(run.get("status") or "") != status:
        return False
    return True


def load_action_run_history(
    *,
    limit: int = 50,
    action_id: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    root = _artifact_root()
    safe_limit = max(1, min(limit, 200))
    runs: list[dict[str, Any]] = []
    for path in _candidate_files(root):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        run = _normalize_action_run(root, path, payload)
        if not _matches_filters(run, action_id=action_id, status=status):
            continue
        runs.append(run)
        if len(runs) >= safe_limit:
            break

    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "ok" if runs else "no_data",
        "count": len(runs),
        "filters": {
            "action_id": action_id,
            "status": status,
        },
        "runs": runs,
    }


def load_action_run_by_id(run_id: str) -> dict[str, Any] | None:
    root = _artifact_root()
    for path in _candidate_files(root):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        source_path = _source_path(root, path)
        if _run_id(source_path) == run_id:
            return _normalize_action_run(root, path, payload)
    return None


def load_action_run_from_path(path: Path) -> dict[str, Any] | None:
    root = _artifact_root()
    payload = _safe_read_json(path)
    if payload is None:
        return None
    return _normalize_action_run(root, path, payload)
