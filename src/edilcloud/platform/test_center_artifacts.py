from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from django.conf import settings


LOADTEST_ARTIFACT_GLOBS = (
    ".tmp/test-center/loadtests/**/*.json",
    "docs/performance-history/loadtests/**/*.json",
)
QUALITY_ARTIFACT_GLOBS = (
    ".tmp/test-center/quality/**/*.json",
    "docs/performance-history/quality/**/*.json",
)


def _artifact_root() -> Path:
    configured = getattr(settings, "TEST_CENTER_ARTIFACT_DIR", "")
    if configured:
        return Path(str(configured)).resolve()
    return Path(getattr(settings, "BASE_DIR", ".")).resolve()


def _candidate_files(root: Path) -> list[Path]:
    return _candidate_files_for(root, LOADTEST_ARTIFACT_GLOBS)


def _candidate_files_for(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    for pattern in patterns:
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


def _report_id(source_path: str) -> str:
    return hashlib.sha256(source_path.encode("utf-8")).hexdigest()[:16]


def _extract_overall(payload: dict[str, Any]) -> dict[str, Any]:
    overall = payload.get("overall")
    if isinstance(overall, dict):
        return overall
    stages = payload.get("stages")
    if isinstance(stages, list) and stages:
        stage = stages[-1]
        if isinstance(stage, dict):
            return {
                "requests": int(stage.get("total_requests") or stage.get("requests") or 0),
                "failures": int(stage.get("total_failures") or stage.get("failures") or 0),
                "failure_ratio": float(stage.get("failure_ratio") or 0.0),
                "avg_ms": float(stage.get("avg_ms") or 0.0),
                "p50_ms": float(stage.get("p50_ms") or 0.0),
                "p95_ms": float(stage.get("p95_ms") or 0.0),
                "p99_ms": float(stage.get("p99_ms") or 0.0),
                "max_ms": float(stage.get("max_ms") or 0.0),
            }
    return {
        "requests": 0,
        "failures": 0,
        "failure_ratio": 0.0,
        "avg_ms": 0.0,
        "p50_ms": 0.0,
        "p95_ms": 0.0,
        "p99_ms": 0.0,
        "max_ms": 0.0,
    }


def _report_status(payload: dict[str, Any], overall: dict[str, Any]) -> str:
    explicit_status = str(payload.get("status") or "").lower()
    if explicit_status in {"pass", "fail", "warning"}:
        return explicit_status
    if payload.get("breaking_stage") is not None:
        return "fail"
    if int(overall.get("requests") or 0) <= 0:
        return "no_data"
    if float(overall.get("failure_ratio") or 0.0) > 0.01:
        return "fail"
    return "pass"


def _report_focus(payload: dict[str, Any], overall: dict[str, Any], status: str) -> list[str]:
    focus = [str(item) for item in payload.get("focus", []) if isinstance(item, str)]
    if status == "no_data":
        focus.append("Nessun report Locust normalizzato disponibile.")
    if status == "fail" and not focus:
        focus.append(
            "Ultimo load test fallito: failure ratio {ratio}, p95 {p95} ms.".format(
                ratio=overall.get("failure_ratio", 0.0),
                p95=overall.get("p95_ms", 0.0),
            )
        )
    return focus[:6]


def _compact_artifacts(payload: dict[str, Any]) -> dict[str, str]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in artifacts.items()
        if isinstance(value, str) and value
    }


def _string_list(value: Any, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:limit] if isinstance(item, str)]


def _dict_list(value: Any, limit: int = 100) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, dict)]


def _normalize_loadtest_report(
    root: Path,
    path: Path,
    payload: dict[str, Any],
    *,
    include_detail: bool = False,
) -> dict[str, Any]:
    overall = _extract_overall(payload)
    status = _report_status(payload, overall)
    source_path = _source_path(root, path)
    report = {
        "id": _report_id(source_path),
        "status": status,
        "data_state": "live",
        "engine": str(payload.get("engine") or "python"),
        "profile": str(payload.get("profile") or payload.get("label") or "unknown"),
        "generated_at": payload.get("generated_at"),
        "source_path": source_path,
        "summary": {
            "requests": int(overall.get("requests") or 0),
            "failures": int(overall.get("failures") or 0),
            "failure_ratio": float(overall.get("failure_ratio") or 0.0),
            "p95_ms": float(overall.get("p95_ms") or 0.0),
            "p99_ms": float(overall.get("p99_ms") or 0.0),
            "users": int(payload.get("users") or 0),
            "duration_seconds": float(payload.get("duration_seconds") or 0.0),
        },
        "artifacts": _compact_artifacts(payload),
        "focus": _report_focus(payload, overall, status),
    }
    if not include_detail:
        return report

    process = payload.get("process") if isinstance(payload.get("process"), dict) else {}
    scenario = payload.get("scenario") if isinstance(payload.get("scenario"), dict) else {}
    report.update(
        {
            "host": payload.get("host"),
            "shape": payload.get("shape"),
            "thresholds": (
                payload.get("thresholds") if isinstance(payload.get("thresholds"), dict) else {}
            ),
            "scenario": scenario,
            "endpoints": _dict_list(payload.get("endpoints"), limit=250),
            "failures": _dict_list(payload.get("failures"), limit=100),
            "stages": _dict_list(payload.get("stages"), limit=100),
            "process": {
                "returncode": process.get("returncode"),
                "stdout_tail": str(process.get("stdout_tail") or "")[-4000:],
                "stderr_tail": str(process.get("stderr_tail") or "")[-4000:],
            },
        }
    )
    return report


def _empty_loadtest_report() -> dict[str, Any]:
    return {
        "id": None,
        "status": "no_data",
        "data_state": "no_data",
        "engine": "locust",
        "profile": None,
        "generated_at": None,
        "source_path": None,
        "summary": {
            "requests": 0,
            "failures": 0,
            "failure_ratio": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "users": 0,
            "duration_seconds": 0.0,
        },
        "artifacts": {},
        "focus": ["Nessun report Locust normalizzato disponibile."],
    }


def load_latest_loadtest_report() -> dict[str, Any]:
    root = _artifact_root()
    for path in _candidate_files(root):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        return _normalize_loadtest_report(root, path, payload)
    return _empty_loadtest_report()


def load_loadtest_history(limit: int = 25) -> dict[str, Any]:
    root = _artifact_root()
    reports: list[dict[str, Any]] = []
    for path in _candidate_files(root):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        reports.append(_normalize_loadtest_report(root, path, payload))
        if len(reports) >= limit:
            break
    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "ok" if reports else "no_data",
        "count": len(reports),
        "reports": reports,
    }


def load_loadtest_report_by_id(run_id: str) -> dict[str, Any] | None:
    root = _artifact_root()
    for path in _candidate_files(root):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        source_path = _source_path(root, path)
        if _report_id(source_path) == run_id:
            return _normalize_loadtest_report(root, path, payload, include_detail=True)
    return None


def _normalize_command_result(command: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(command.get("key") or command.get("label") or "command"),
        "label": str(command.get("label") or command.get("key") or "Command"),
        "status": str(command.get("status") or "unknown"),
        "returncode": command.get("returncode"),
        "duration_seconds": float(command.get("duration_seconds") or 0.0),
        "command": str(command.get("command") or ""),
        "cwd": str(command.get("cwd") or ""),
        "stdout_tail": str(command.get("stdout_tail") or "")[-4000:],
        "stderr_tail": str(command.get("stderr_tail") or "")[-4000:],
    }


def _quality_status(payload: dict[str, Any], commands: list[dict[str, Any]]) -> str:
    explicit_status = str(payload.get("status") or "").lower()
    if explicit_status in {"pass", "fail", "warning", "skipped"}:
        return explicit_status
    if not commands:
        return "no_data"
    if any(command["status"] == "fail" for command in commands):
        return "fail"
    if any(command["status"] in {"warning", "skipped"} for command in commands):
        return "warning"
    return "pass"


def _normalize_quality_report(
    root: Path,
    path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    source_path = _source_path(root, path)
    commands = [
        _normalize_command_result(item)
        for item in payload.get("commands", [])
        if isinstance(item, dict)
    ]
    status = _quality_status(payload, commands)
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    focus = _string_list(payload.get("focus"), limit=8)
    if status == "fail" and not focus:
        failing = [command["label"] for command in commands if command["status"] == "fail"]
        focus.append("Quality suite fallita: " + ", ".join(failing[:3]))
    if status in {"no_data", "skipped"} and not focus:
        focus.append("Nessun report quality eseguibile disponibile.")
    return {
        "id": _report_id(source_path),
        "status": status,
        "data_state": "live",
        "engine": str(payload.get("engine") or "quality-suite"),
        "platform": str(payload.get("platform") or "unknown"),
        "target": payload.get("target"),
        "suite": str(payload.get("suite") or "quality"),
        "generated_at": payload.get("generated_at"),
        "source_path": source_path,
        "summary": {
            "commands": int(summary.get("commands") or len(commands)),
            "passed": int(summary.get("passed") or sum(command["status"] == "pass" for command in commands)),
            "failed": int(summary.get("failed") or sum(command["status"] == "fail" for command in commands)),
            "skipped": int(
                summary.get("skipped")
                or sum(command["status"] == "skipped" for command in commands)
            ),
            "duration_seconds": float(summary.get("duration_seconds") or 0.0),
        },
        "commands": commands,
        "focus": focus[:8],
    }


def _empty_quality_report(platform: str, target: str | None = None) -> dict[str, Any]:
    return {
        "id": None,
        "status": "no_data",
        "data_state": "no_data",
        "engine": "quality-suite",
        "platform": platform,
        "target": target,
        "suite": "quality",
        "generated_at": None,
        "source_path": None,
        "summary": {
            "commands": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "duration_seconds": 0.0,
        },
        "commands": [],
        "focus": ["Nessun report quality normalizzato disponibile."],
    }


def load_latest_quality_reports() -> dict[str, Any]:
    root = _artifact_root()
    latest: dict[str, dict[str, Any]] = {}
    for path in _candidate_files_for(root, QUALITY_ARTIFACT_GLOBS):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        report = _normalize_quality_report(root, path, payload)
        platform = str(report["platform"])
        target = report.get("target")
        key = f"{platform}:{target}" if target else platform
        latest.setdefault(key, report)

    return {
        "backend": latest.get("backend") or _empty_quality_report("backend"),
        "frontend-next": latest.get("frontend-next") or _empty_quality_report("frontend-next"),
        "flutter": {
            "android": latest.get("flutter:android") or _empty_quality_report("flutter", "android"),
            "ios": latest.get("flutter:ios") or _empty_quality_report("flutter", "ios"),
        },
    }


def _matches_quality_filter(
    report: dict[str, Any],
    *,
    platform: str | None = None,
    target: str | None = None,
) -> bool:
    if platform and str(report.get("platform") or "") != platform:
        return False
    if target and str(report.get("target") or "") != target:
        return False
    return True


def load_quality_history(
    *,
    limit: int = 25,
    platform: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    root = _artifact_root()
    reports: list[dict[str, Any]] = []
    safe_limit = max(1, min(limit, 100))
    for path in _candidate_files_for(root, QUALITY_ARTIFACT_GLOBS):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        report = _normalize_quality_report(root, path, payload)
        if not _matches_quality_filter(report, platform=platform, target=target):
            continue
        reports.append(report)
        if len(reports) >= safe_limit:
            break

    return {
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "ok" if reports else "no_data",
        "count": len(reports),
        "filters": {
            "platform": platform,
            "target": target,
        },
        "reports": reports,
    }


def load_quality_report_by_id(run_id: str) -> dict[str, Any] | None:
    root = _artifact_root()
    for path in _candidate_files_for(root, QUALITY_ARTIFACT_GLOBS):
        payload = _safe_read_json(path)
        if payload is None:
            continue
        source_path = _source_path(root, path)
        if _report_id(source_path) == run_id:
            return _normalize_quality_report(root, path, payload)
    return None
