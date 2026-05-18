from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from django.conf import settings
import requests

from edilcloud.platform.test_center_action_runs import (
    LOADTEST_PROFILES,
    TestCenterActionRunError,
    _artifact_root,
    _command_text,
    _timestamp,
    _utc_now,
)
from edilcloud.platform.test_center_run_ledger import load_action_run_from_path


CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "backend-quality",
        "label": "Backend quality",
        "platform": "backend",
        "target": None,
        "category": "quality",
        "operation": "rerun_quality_suite",
        "execution": "local",
        "runner": "backend",
        "suite": "backend",
        "risk": "low",
        "description": "Ruff e pytest backend mirati.",
    },
    {
        "id": "frontend-next-quality",
        "label": "Frontend Next quality",
        "platform": "frontend-next",
        "target": None,
        "category": "quality",
        "operation": "rerun_quality_suite",
        "execution": "remote",
        "runner": "github-actions",
        "suite": "frontend-next",
        "workflow_repo": "alecoti/edilcloud-next",
        "workflow_id": "test-center-quality.yml",
        "risk": "low",
        "description": "ESLint mirato e build Next su runner dedicato.",
    },
    {
        "id": "flutter-android-quality",
        "label": "Flutter Android quality",
        "platform": "flutter",
        "target": "android",
        "category": "quality",
        "operation": "rerun_quality_suite",
        "execution": "remote",
        "runner": "github-actions",
        "suite": "flutter-android",
        "workflow_repo": "alecoti/edilcloud-flutter",
        "workflow_id": "test-center-quality.yml",
        "risk": "low",
        "description": "Analyze, test e build APK debug su runner Android.",
    },
    {
        "id": "flutter-ios-quality",
        "label": "Flutter iOS quality",
        "platform": "flutter",
        "target": "ios",
        "category": "quality",
        "operation": "rerun_quality_suite",
        "execution": "remote",
        "runner": "github-actions",
        "suite": "flutter-ios",
        "workflow_repo": "alecoti/edilcloud-flutter",
        "workflow_id": "test-center-quality.yml",
        "risk": "low",
        "description": "Analyze, test e build iOS no-codesign su runner macOS.",
    },
    {
        "id": "locust-auth-burst",
        "label": "Locust auth burst",
        "platform": "backend",
        "target": None,
        "category": "performance",
        "operation": "rerun_loadtest_suite",
        "execution": "local",
        "runner": "backend",
        "profile": "auth-burst",
        "risk": "medium",
        "description": "Raffica controllata di login.",
    },
    {
        "id": "locust-read-heavy",
        "label": "Locust read heavy",
        "platform": "backend",
        "target": None,
        "category": "performance",
        "operation": "rerun_loadtest_suite",
        "execution": "local",
        "runner": "backend",
        "profile": "read-heavy",
        "risk": "medium",
        "description": "Navigazione estesa delle route core in lettura.",
    },
    {
        "id": "locust-mixed-crud",
        "label": "Locust mixed CRUD",
        "platform": "backend",
        "target": None,
        "category": "performance",
        "operation": "rerun_loadtest_suite",
        "execution": "local",
        "runner": "backend",
        "profile": "mixed-crud",
        "risk": "medium",
        "description": "Profilo lettura piu creazione/rimozione controllata di contenuti.",
    },
)


def _catalog_item(item: dict[str, Any]) -> dict[str, Any]:
    remote_configured = bool(
        getattr(settings, "TEST_CENTER_GITHUB_TOKEN", "")
        and getattr(settings, "TEST_CENTER_INGEST_TOKEN", "")
    )
    launchable = item["execution"] == "local" or remote_configured
    return {
        **item,
        "launchable": launchable,
        "blocked_by": (
            []
            if launchable
            else ["TEST_CENTER_GITHUB_TOKEN e TEST_CENTER_INGEST_TOKEN non configurati."]
        ),
    }


def build_test_center_catalog() -> dict[str, Any]:
    suites = [_catalog_item(item) for item in CATALOG]
    return {
        "generated_at": _utc_now(),
        "status": "ok" if all(item["launchable"] for item in suites) else "attention",
        "summary": {
            "total": len(suites),
            "launchable": sum(item["launchable"] for item in suites),
            "local": sum(item["execution"] == "local" for item in suites),
            "remote": sum(item["execution"] == "remote" for item in suites),
        },
        "suites": suites,
    }


def get_catalog_suite(suite_id: str) -> dict[str, Any] | None:
    for item in CATALOG:
        if item["id"] == suite_id:
            return _catalog_item(item)
    return None


def _write_run_payload(suite: dict[str, Any], payload: dict[str, Any]) -> tuple[str, Path]:
    run_name = f"{_timestamp()}--catalog-{suite['id']}--running"
    run_dir = _artifact_root() / ".tmp" / "test-center" / "action-runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "action-run.json"
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return run_name, artifact_path


def _local_command(
    suite: dict[str, Any],
    *,
    loadtest_host: str,
    loadtest_users: int,
    loadtest_spawn_rate: float,
    loadtest_run_time: str,
) -> list[str]:
    if suite["category"] == "quality":
        return [
            sys.executable,
            "scripts/run_quality_suite.py",
            "--suite",
            str(suite["suite"]),
            "--fail-on-threshold",
        ]
    profile = str(suite["profile"])
    if profile not in LOADTEST_PROFILES:
        raise TestCenterActionRunError(f"Profilo Locust non supportato: {profile}.")
    return [
        sys.executable,
        "scripts/run_locust_suite.py",
        "--profile",
        profile,
        "--host",
        loadtest_host,
        "--users",
        str(max(1, min(loadtest_users, 250))),
        "--spawn-rate",
        str(max(0.1, min(loadtest_spawn_rate, 100.0))),
        "--run-time",
        loadtest_run_time.strip() or "2m",
        "--fail-on-threshold",
    ]


def _base_payload(
    suite: dict[str, Any],
    *,
    actor_id: str,
    actor_label: str,
    command: list[str],
) -> dict[str, Any]:
    return {
        "status": "running",
        "mode": "dry_run",
        "action_id": f"catalog:{suite['id']}",
        "issue_id": None,
        "operation": suite["operation"],
        "platform": suite["platform"],
        "target": suite["target"],
        "category": suite["category"],
        "generated_at": _utc_now(),
        "started_at": _utc_now(),
        "finished_at": None,
        "duration_seconds": 0.0,
        "actor": {"kind": "superuser", "id": actor_id, "label": actor_label or actor_id},
        "command": _command_text(command),
        "cwd": str(Path(getattr(settings, "BASE_DIR", ".")).resolve()),
        "returncode": None,
        "summary": f"Avvio catalogo: {suite['label']}.",
        "stdout_tail": "",
        "stderr_tail": "",
        "artifacts": {},
        "evidence": [f"Catalog suite: {suite['id']}", f"Runner: {suite['runner']}"],
        "next_step": "Attendere il completamento del runner e leggere i log della run.",
        "audit": {
            "will_modify_code": False,
            "will_touch_production": False,
            "approval_required": suite["risk"] != "low",
            "approved_by": None,
        },
    }


def launch_catalog_suite(
    *,
    suite_id: str,
    actor_id: str,
    actor_label: str,
    approved_by: str | None,
    loadtest_host: str,
    loadtest_users: int,
    loadtest_spawn_rate: float,
    loadtest_run_time: str,
) -> dict[str, Any]:
    suite = get_catalog_suite(suite_id)
    if suite is None:
        raise TestCenterActionRunError(f"Suite catalogo non trovata: {suite_id}.")
    if not suite["launchable"]:
        raise TestCenterActionRunError("; ".join(suite["blocked_by"]))
    if suite["risk"] != "low" and not approved_by:
        raise TestCenterActionRunError("La suite richiede approvazione operatore.")

    command = (
        _local_command(
            suite,
            loadtest_host=loadtest_host,
            loadtest_users=loadtest_users,
            loadtest_spawn_rate=loadtest_spawn_rate,
            loadtest_run_time=loadtest_run_time,
        )
        if suite["execution"] == "local"
        else ["github-actions", str(suite["workflow_repo"]), str(suite["workflow_id"])]
    )
    payload = _base_payload(suite, actor_id=actor_id, actor_label=actor_label, command=command)
    payload["audit"]["approved_by"] = approved_by or None
    run_name, artifact_path = _write_run_payload(suite, payload)
    if suite["execution"] == "local":
        subprocess.Popen(
            [
                sys.executable,
                "scripts/run_test_center_suite.py",
                "--suite-id",
                suite_id,
                "--run-name",
                run_name,
                "--actor-id",
                actor_id,
                "--actor-label",
                actor_label or actor_id,
                *(["--approved-by", approved_by] if approved_by else []),
                "--loadtest-host",
                loadtest_host,
                "--loadtest-users",
                str(loadtest_users),
                "--loadtest-spawn-rate",
                str(loadtest_spawn_rate),
                "--loadtest-run-time",
                loadtest_run_time,
            ],
            cwd=Path(getattr(settings, "BASE_DIR", ".")).resolve(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        dispatch_remote_suite(suite, run_name=run_name)
    run = load_action_run_from_path(artifact_path)
    if run is None:
        raise TestCenterActionRunError("Run catalogo avviata ma artifact non leggibile.")
    return run


def dispatch_remote_suite(suite: dict[str, Any], *, run_name: str) -> None:
    token = str(getattr(settings, "TEST_CENTER_GITHUB_TOKEN", "") or "").strip()
    ingest_token = str(getattr(settings, "TEST_CENTER_INGEST_TOKEN", "") or "").strip()
    if not token or not ingest_token:
        raise TestCenterActionRunError(
            "Runner remoto non configurato: mancano token GitHub o ingest Test Center."
        )
    response = requests.post(
        "https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches".format(
            repo=suite["workflow_repo"],
            workflow=suite["workflow_id"],
        ),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "ref": "main",
            "inputs": {
                "suite": suite["suite"],
                "catalog_run_name": run_name,
                "ingest_url": (
                    str(getattr(settings, "BACKEND_PUBLIC_URL", "")).rstrip("/")
                    + "/api/v1/test-center/ingest/quality"
                ),
            },
        },
        timeout=15,
    )
    if response.status_code not in {204}:
        raise TestCenterActionRunError(
            f"Dispatch runner remoto fallito ({response.status_code})."
        )


def ingest_quality_report(payload: dict[str, Any], *, run_name: str | None = None) -> Path:
    required_fields = {"engine", "status", "platform", "suite", "summary", "commands"}
    missing = sorted(required_fields.difference(payload))
    if missing:
        raise TestCenterActionRunError(
            "Report quality remoto incompleto: " + ", ".join(missing)
        )
    generated_at = str(payload.get("generated_at") or datetime.now(UTC).isoformat())
    slug = str(payload.get("platform") or "external")
    target = payload.get("target")
    suffix = f"-{target}" if target else ""
    directory = run_name or f"{_timestamp()}--external-{slug}{suffix}"
    report_dir = _artifact_root() / ".tmp" / "test-center" / "quality" / directory
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {**payload, "generated_at": generated_at}
    artifact_path = report_dir / "quality-report.json"
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return artifact_path
