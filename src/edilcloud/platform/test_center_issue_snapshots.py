from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings


ISSUE_SNAPSHOT_ARTIFACT_GLOBS = (
    ".tmp/test-center/issues/**/*.json",
    "docs/performance-history/issues/**/*.json",
)


def _artifact_root() -> Path:
    configured = getattr(settings, "TEST_CENTER_ARTIFACT_DIR", "")
    if configured:
        return Path(str(configured)).resolve()
    return Path(getattr(settings, "BASE_DIR", ".")).resolve()


def _candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in ISSUE_SNAPSHOT_ARTIFACT_GLOBS:
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


def _snapshot_id(source_path: str) -> str:
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]


def _issue_key(issue: dict[str, Any]) -> str:
    return str(issue.get("id") or "")


def _verification_key(issue: dict[str, Any]) -> tuple[str | None, str | None]:
    verification = issue.get("verification")
    if not isinstance(verification, dict):
        return (None, None)
    return (
        str(verification.get("run_id") or "") or None,
        str(verification.get("status") or "") or None,
    )


def _compact_issue(issue: dict[str, Any]) -> dict[str, Any]:
    verification = issue.get("verification")
    return {
        "id": str(issue.get("id") or ""),
        "status": str(issue.get("status") or ""),
        "severity": str(issue.get("severity") or ""),
        "platform": str(issue.get("platform") or ""),
        "target": issue.get("target"),
        "category": str(issue.get("category") or ""),
        "title": str(issue.get("title") or ""),
        "summary": str(issue.get("summary") or ""),
        "detected_at": issue.get("detected_at"),
        "verification": verification if isinstance(verification, dict) else None,
    }


def _compact_resolved_issue(issue: dict[str, Any]) -> dict[str, Any]:
    verification = issue.get("verification")
    return {
        "id": str(issue.get("id") or ""),
        "status": str(issue.get("status") or ""),
        "severity": str(issue.get("severity") or ""),
        "platform": str(issue.get("platform") or ""),
        "target": issue.get("target"),
        "category": str(issue.get("category") or ""),
        "title": str(issue.get("title") or ""),
        "summary": str(issue.get("summary") or ""),
        "resolved_at": issue.get("resolved_at"),
        "verification": verification if isinstance(verification, dict) else None,
    }


def _semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    issues = [
        _compact_issue(issue)
        for issue in payload.get("issues", [])
        if isinstance(issue, dict) and _issue_key(issue)
    ]
    resolved = [
        _compact_resolved_issue(issue)
        for issue in payload.get("recently_resolved", [])
        if isinstance(issue, dict) and _issue_key(issue)
    ]
    return {
        "status": str(payload.get("status") or ""),
        "issues": sorted(issues, key=lambda issue: issue["id"]),
        "recently_resolved": sorted(resolved, key=lambda issue: issue["id"]),
    }


def _signature(payload: dict[str, Any]) -> str:
    semantic = _semantic_payload(payload)
    encoded = json.dumps(semantic, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _issue_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item["id"]): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def _change_items(
    issue_ids: set[str],
    current: dict[str, dict[str, Any]],
    previous: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    source = current or previous
    return [source[issue_id] for issue_id in sorted(issue_ids) if issue_id in source]


def _build_changes(
    current_issues: list[dict[str, Any]],
    current_resolved: list[dict[str, Any]],
    previous_snapshot: dict[str, Any] | None,
) -> dict[str, list[dict[str, Any]]]:
    current_open = _issue_map(current_issues)
    current_closed = _issue_map(current_resolved)
    previous_open = _issue_map(
        previous_snapshot.get("issues", [])
        if isinstance(previous_snapshot, dict)
        else []
    )
    previous_closed = _issue_map(
        previous_snapshot.get("recently_resolved", [])
        if isinstance(previous_snapshot, dict)
        else []
    )

    current_open_ids = set(current_open)
    previous_open_ids = set(previous_open)
    current_closed_ids = set(current_closed)
    previous_closed_ids = set(previous_closed)

    opened_ids = current_open_ids - previous_open_ids - previous_closed_ids
    reopened_ids = current_open_ids & previous_closed_ids
    resolved_ids = current_closed_ids & previous_open_ids
    verified_ids = {
        issue_id
        for issue_id in current_open_ids & previous_open_ids
        if _verification_key(current_open[issue_id])
        != _verification_key(previous_open[issue_id])
        and _verification_key(current_open[issue_id]) != (None, None)
    }

    # Alla prima fotografia considero aperte le issue correnti, cosi lo storico
    # parte gia da uno stato leggibile invece che da una riga muta.
    if previous_snapshot is None:
        opened_ids = current_open_ids

    return {
        "opened": _change_items(opened_ids, current_open, previous_open),
        "verified": _change_items(verified_ids, current_open, previous_open),
        "resolved": _change_items(resolved_ids, current_closed, previous_open),
        "reopened": _change_items(reopened_ids, current_open, previous_closed),
    }


def _normalize_snapshot(
    root: Path,
    path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    source_path = _source_path(root, path)
    changes = payload.get("changes")
    changes = changes if isinstance(changes, dict) else {}
    return {
        "id": _snapshot_id(source_path),
        "signature": str(payload.get("signature") or ""),
        "generated_at": payload.get("generated_at"),
        "status": str(payload.get("status") or "unknown"),
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "issues": [
            item for item in payload.get("issues", []) if isinstance(item, dict)
        ],
        "recently_resolved": [
            item
            for item in payload.get("recently_resolved", [])
            if isinstance(item, dict)
        ],
        "changes": {
            "opened": [item for item in changes.get("opened", []) if isinstance(item, dict)],
            "verified": [
                item for item in changes.get("verified", []) if isinstance(item, dict)
            ],
            "resolved": [
                item for item in changes.get("resolved", []) if isinstance(item, dict)
            ],
            "reopened": [
                item for item in changes.get("reopened", []) if isinstance(item, dict)
            ],
        },
        "source_path": source_path,
    }


def _latest_snapshot(root: Path) -> dict[str, Any] | None:
    for path in _candidate_files(root):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        return _normalize_snapshot(root, path, payload)
    return None


def record_issue_snapshot(payload: dict[str, Any]) -> Path | None:
    root = _artifact_root()
    signature = _signature(payload)
    latest = _latest_snapshot(root)
    if latest and latest.get("signature") == signature:
        return None

    issues = [
        _compact_issue(issue)
        for issue in payload.get("issues", [])
        if isinstance(issue, dict) and _issue_key(issue)
    ]
    resolved = [
        _compact_resolved_issue(issue)
        for issue in payload.get("recently_resolved", [])
        if isinstance(issue, dict) and _issue_key(issue)
    ]
    generated_at = str(payload.get("generated_at") or datetime.now(UTC).isoformat())
    timestamp = (
        generated_at.replace(":", "")
        .replace("-", "")
        .replace("T", "-")
        .replace("Z", "")
    )
    artifact_path = (
        root
        / ".tmp"
        / "test-center"
        / "issues"
        / f"{timestamp}--{signature}"
        / "issue-snapshot.json"
    )
    snapshot = {
        "signature": signature,
        "generated_at": generated_at,
        "status": str(payload.get("status") or "unknown"),
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "issues": issues,
        "recently_resolved": resolved,
        "changes": _build_changes(issues, resolved, latest),
    }

    try:
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    except OSError:
        return None
    return artifact_path


def load_issue_snapshot_history(*, limit: int = 25) -> dict[str, Any]:
    root = _artifact_root()
    safe_limit = max(1, min(limit, 200))
    snapshots: list[dict[str, Any]] = []
    for path in _candidate_files(root):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        snapshots.append(_normalize_snapshot(root, path, payload))
        if len(snapshots) >= safe_limit:
            break

    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "ok" if snapshots else "no_data",
        "count": len(snapshots),
        "snapshots": snapshots,
    }
