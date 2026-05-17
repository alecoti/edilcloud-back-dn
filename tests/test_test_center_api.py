import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from edilcloud.platform.telemetry import reset_metrics


def write_locust_report(root: Path, run_name: str, payload: dict) -> None:
    report_dir = root / ".tmp" / "test-center" / "loadtests" / run_name
    report_dir.mkdir(parents=True)
    (report_dir / "locust-report.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def write_quality_report(root: Path, run_name: str, payload: dict) -> None:
    report_dir = root / ".tmp" / "test-center" / "quality" / run_name
    report_dir.mkdir(parents=True)
    (report_dir / "quality-report.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def write_action_run(root: Path, run_name: str, payload: dict) -> None:
    report_dir = root / ".tmp" / "test-center" / "action-runs" / run_name
    report_dir.mkdir(parents=True)
    (report_dir / "action-run.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def auth_headers(client: Client, *, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": email,
                "password": password,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    token = response.json()["token"]
    return {"HTTP_AUTHORIZATION": f"JWT {token}"}


@pytest.mark.django_db
def test_test_center_requires_authentication():
    client = Client()

    response = client.get("/api/v1/test-center/overview")

    assert response.status_code == 401


@pytest.mark.django_db
def test_test_center_requires_superuser():
    get_user_model().objects.create_user(
        email="operator@example.com",
        password="devpass123",
        username="operator",
    )
    client = Client()
    headers = auth_headers(client, email="operator@example.com", password="devpass123")

    response = client.get("/api/v1/test-center/overview", **headers)

    assert response.status_code == 403
    assert "superuser" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_test_center_overview_exposes_live_backend_and_pending_surfaces():
    reset_metrics()
    get_user_model().objects.create_superuser(
        email="ops@example.com",
        password="devpass123",
        username="ops",
    )
    client = Client()
    headers = auth_headers(client, email="ops@example.com", password="devpass123")

    assert client.get("/api/v1/health").status_code == 200
    response = client.get("/api/v1/test-center/overview", **headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["overall_status"] in {"ok", "warning", "critical"}
    assert payload["summary"]["platform_count"] == 3
    assert payload["summary"]["live_platforms"] == 1
    assert payload["summary"]["runtime_rules_checked"] >= 1

    platforms = {item["key"]: item for item in payload["platforms"]}
    assert platforms["backend"]["data_state"] == "live"
    assert platforms["backend"]["checks"]
    assert platforms["frontend-next"]["status"] == "no_data"
    assert platforms["flutter"]["targets"] == [
        {"key": "android", "label": "Android", "status": "no_data"},
        {"key": "ios", "label": "iOS", "status": "no_data"},
    ]
    assert isinstance(payload["performance"]["top_slowest"], list)
    assert payload["loadtests"]["status"] in {"no_data", "pass", "fail", "warning"}
    assert payload["quality"]["flutter"]["android"]["status"] == "no_data"
    assert payload["recommendations"]


@pytest.mark.django_db
def test_test_center_overview_reads_latest_locust_artifact(settings, tmp_path):
    artifact_dir = Path(tmp_path)
    write_locust_report(
        artifact_dir,
        "run-a",
        {
            "engine": "locust",
            "status": "pass",
            "generated_at": "2026-05-17T09:00:00Z",
            "profile": "read-heavy",
            "users": 12,
            "duration_seconds": 120.5,
            "overall": {
                "requests": 240,
                "failures": 0,
                "failure_ratio": 0.0,
                "p95_ms": 420.0,
                "p99_ms": 680.0,
            },
            "artifacts": {"html": "locust-report.html"},
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.locust@example.com",
        password="devpass123",
        username="ops-locust",
    )
    client = Client()
    headers = auth_headers(client, email="ops.locust@example.com", password="devpass123")

    response = client.get("/api/v1/test-center/overview", **headers)

    assert response.status_code == 200
    loadtests = response.json()["loadtests"]
    assert loadtests["status"] == "pass"
    assert loadtests["engine"] == "locust"
    assert loadtests["profile"] == "read-heavy"
    assert loadtests["summary"]["requests"] == 240
    assert loadtests["summary"]["users"] == 12
    assert loadtests["id"]


@pytest.mark.django_db
def test_test_center_overview_reads_quality_artifacts_for_frontend_and_flutter(
    settings,
    tmp_path,
):
    artifact_dir = Path(tmp_path)
    write_quality_report(
        artifact_dir,
        "backend",
        {
            "engine": "quality-suite",
            "status": "pass",
            "generated_at": "2026-05-17T09:00:00Z",
            "platform": "backend",
            "suite": "quality",
            "summary": {"commands": 2, "passed": 2, "failed": 0, "skipped": 0},
            "commands": [
                {"key": "backend-ruff", "label": "Backend Ruff", "status": "pass"},
                {"key": "backend-pytest", "label": "Backend pytest", "status": "pass"},
            ],
        },
    )
    write_quality_report(
        artifact_dir,
        "frontend",
        {
            "engine": "quality-suite",
            "status": "pass",
            "generated_at": "2026-05-17T09:05:00Z",
            "platform": "frontend-next",
            "suite": "quality",
            "summary": {"commands": 2, "passed": 2, "failed": 0, "skipped": 0},
            "commands": [
                {"key": "frontend-eslint", "label": "Frontend ESLint", "status": "pass"},
                {"key": "frontend-build", "label": "Frontend build", "status": "pass"},
            ],
        },
    )
    write_quality_report(
        artifact_dir,
        "flutter-android",
        {
            "engine": "quality-suite",
            "status": "pass",
            "generated_at": "2026-05-17T09:10:00Z",
            "platform": "flutter",
            "target": "android",
            "suite": "quality",
            "summary": {"commands": 3, "passed": 3, "failed": 0, "skipped": 0},
            "commands": [
                {"key": "flutter-analyze", "label": "Flutter analyze", "status": "pass"},
                {"key": "flutter-test", "label": "Flutter test", "status": "pass"},
                {
                    "key": "flutter-android-build",
                    "label": "Flutter Android debug build",
                    "status": "pass",
                },
            ],
        },
    )
    write_quality_report(
        artifact_dir,
        "flutter-ios",
        {
            "engine": "quality-suite",
            "status": "fail",
            "generated_at": "2026-05-17T09:15:00Z",
            "platform": "flutter",
            "target": "ios",
            "suite": "quality",
            "summary": {"commands": 3, "passed": 2, "failed": 1, "skipped": 0},
            "commands": [
                {"key": "flutter-analyze", "label": "Flutter analyze", "status": "pass"},
                {"key": "flutter-test", "label": "Flutter test", "status": "pass"},
                {
                    "key": "flutter-ios-build",
                    "label": "Flutter iOS debug build",
                    "status": "fail",
                    "returncode": 1,
                    "stderr_tail": "codesign failure",
                },
            ],
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.quality@example.com",
        password="devpass123",
        username="ops-quality",
    )
    client = Client()
    headers = auth_headers(client, email="ops.quality@example.com", password="devpass123")

    response = client.get("/api/v1/test-center/overview", **headers)

    assert response.status_code == 200
    payload = response.json()
    platforms = {item["key"]: item for item in payload["platforms"]}
    assert platforms["frontend-next"]["data_state"] == "live"
    assert platforms["frontend-next"]["status"] == "ok"
    assert platforms["flutter"]["status"] == "critical"
    assert platforms["flutter"]["targets"] == [
        {"key": "android", "label": "Android", "status": "ok"},
        {"key": "ios", "label": "iOS", "status": "critical"},
    ]
    assert payload["quality"]["frontend-next"]["summary"]["passed"] == 2
    assert payload["quality"]["flutter"]["ios"]["commands"][2]["stderr_tail"] == "codesign failure"

    flutter_detail = client.get("/api/v1/test-center/platforms/flutter", **headers)
    assert flutter_detail.status_code == 200
    assert flutter_detail.json()["quality"]["ios"]["status"] == "fail"


@pytest.mark.django_db
def test_test_center_quality_history_filter_and_detail(settings, tmp_path):
    artifact_dir = Path(tmp_path)
    write_quality_report(
        artifact_dir,
        "backend",
        {
            "engine": "quality-suite",
            "status": "pass",
            "generated_at": "2026-05-17T09:00:00Z",
            "platform": "backend",
            "suite": "quality",
            "summary": {"commands": 2, "passed": 2, "failed": 0, "skipped": 0},
            "commands": [
                {
                    "key": "backend-ruff",
                    "label": "Backend Ruff",
                    "status": "pass",
                    "stdout_tail": "ruff ok",
                },
                {
                    "key": "backend-pytest",
                    "label": "Backend pytest",
                    "status": "pass",
                    "stdout_tail": "13 passed",
                },
            ],
        },
    )
    write_quality_report(
        artifact_dir,
        "flutter-ios",
        {
            "engine": "quality-suite",
            "status": "fail",
            "generated_at": "2026-05-17T09:15:00Z",
            "platform": "flutter",
            "target": "ios",
            "suite": "quality",
            "summary": {"commands": 3, "passed": 2, "failed": 1, "skipped": 0},
            "commands": [
                {"key": "flutter-analyze", "label": "Flutter analyze", "status": "pass"},
                {"key": "flutter-test", "label": "Flutter test", "status": "pass"},
                {
                    "key": "flutter-ios-build",
                    "label": "Flutter iOS debug build",
                    "status": "fail",
                    "returncode": 1,
                    "command": "flutter build ios --debug",
                    "stderr_tail": "codesign failure",
                },
            ],
            "focus": ["Sbloccare firma iOS nel runner dedicato."],
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.quality.history@example.com",
        password="devpass123",
        username="ops-quality-history",
    )
    client = Client()
    headers = auth_headers(
        client,
        email="ops.quality.history@example.com",
        password="devpass123",
    )

    history_response = client.get("/api/v1/test-center/quality", **headers)

    assert history_response.status_code == 200
    history = history_response.json()
    assert history["status"] == "ok"
    assert history["count"] == 2

    ios_response = client.get(
        "/api/v1/test-center/quality?platform=flutter&target=ios",
        **headers,
    )

    assert ios_response.status_code == 200
    ios_history = ios_response.json()
    assert ios_history["count"] == 1
    assert ios_history["filters"] == {"platform": "flutter", "target": "ios"}
    ios_report = ios_history["reports"][0]
    assert ios_report["platform"] == "flutter"
    assert ios_report["target"] == "ios"
    assert ios_report["status"] == "fail"

    detail_response = client.get(
        f"/api/v1/test-center/quality/{ios_report['id']}",
        **headers,
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["source_path"].endswith("flutter-ios/quality-report.json")
    assert detail["commands"][2]["command"] == "flutter build ios --debug"
    assert detail["commands"][2]["stderr_tail"] == "codesign failure"
    assert detail["focus"] == ["Sbloccare firma iOS nel runner dedicato."]

    missing_response = client.get("/api/v1/test-center/quality/missing", **headers)
    assert missing_response.status_code == 404


@pytest.mark.django_db
def test_test_center_issues_classify_quality_and_loadtest_failures(settings, tmp_path):
    artifact_dir = Path(tmp_path)
    write_locust_report(
        artifact_dir,
        "run-failing",
        {
            "engine": "locust",
            "status": "fail",
            "generated_at": "2026-05-17T10:00:00Z",
            "profile": "mixed-crud",
            "users": 20,
            "duration_seconds": 180.0,
            "overall": {
                "requests": 400,
                "failures": 8,
                "failure_ratio": 0.02,
                "p95_ms": 1400.0,
                "p99_ms": 1900.0,
            },
            "focus": ["Endpoint posts.create oltre soglia."],
        },
    )
    write_quality_report(
        artifact_dir,
        "frontend",
        {
            "engine": "quality-suite",
            "status": "fail",
            "generated_at": "2026-05-17T09:05:00Z",
            "platform": "frontend-next",
            "suite": "quality",
            "summary": {"commands": 2, "passed": 1, "failed": 1, "skipped": 0},
            "commands": [
                {"key": "frontend-eslint", "label": "Frontend ESLint", "status": "pass"},
                {
                    "key": "frontend-build",
                    "label": "Frontend build",
                    "status": "fail",
                    "command": "pnpm build",
                    "stderr_tail": "Type error",
                },
            ],
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.issues@example.com",
        password="devpass123",
        username="ops-issues",
    )
    client = Client()
    headers = auth_headers(client, email="ops.issues@example.com", password="devpass123")

    response = client.get("/api/v1/test-center/issues", **headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "attention"
    assert payload["summary"]["critical"] >= 2
    issues_by_category = {issue["category"]: issue for issue in payload["issues"]}
    assert issues_by_category["performance"]["source"]["kind"] == "loadtest-report"
    assert issues_by_category["performance"]["automation"]["state"] == "manual_review_required"

    frontend_issue = next(
        issue
        for issue in payload["issues"]
        if issue["platform"] == "frontend-next" and issue["category"] == "quality"
    )
    assert frontend_issue["severity"] == "critical"
    assert frontend_issue["suggested_commands"] == ["pnpm build"]
    assert any("Frontend build" in item for item in frontend_issue["evidence"])


@pytest.mark.django_db
def test_test_center_actions_build_dry_run_remediation_registry(settings, tmp_path):
    artifact_dir = Path(tmp_path)
    write_quality_report(
        artifact_dir,
        "frontend",
        {
            "engine": "quality-suite",
            "status": "fail",
            "generated_at": "2026-05-17T09:05:00Z",
            "platform": "frontend-next",
            "suite": "quality",
            "summary": {"commands": 2, "passed": 1, "failed": 1, "skipped": 0},
            "commands": [
                {"key": "frontend-eslint", "label": "Frontend ESLint", "status": "pass"},
                {
                    "key": "frontend-build",
                    "label": "Frontend build",
                    "status": "fail",
                    "command": "pnpm build",
                    "stderr_tail": "Type error",
                },
            ],
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.actions@example.com",
        password="devpass123",
        username="ops-actions",
    )
    client = Client()
    headers = auth_headers(client, email="ops.actions@example.com", password="devpass123")

    response = client.get("/api/v1/test-center/actions", **headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "attention"
    assert payload["summary"]["total"] >= 1
    frontend_action = next(
        action
        for action in payload["actions"]
        if action["platform"] == "frontend-next" and action["category"] == "quality"
    )
    assert frontend_action["mode"] == "dry_run"
    assert frontend_action["state"] == "needs_human_review"
    assert frontend_action["risk"] == "medium"
    assert frontend_action["verification_commands"] == ["pnpm build"]
    assert frontend_action["allowed_operations"] == ["rerun_quality_suite"]
    assert frontend_action["audit"]["will_modify_code"] is False
    assert frontend_action["audit"]["requires_operator_approval"] is True

    detail_response = client.get(
        f"/api/v1/test-center/actions/{frontend_action['id']}",
        **headers,
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == frontend_action["id"]
    assert detail["source_issue"]["severity"] == "critical"
    assert detail["success_criteria"]

    missing_response = client.get("/api/v1/test-center/actions/missing", **headers)
    assert missing_response.status_code == 404


@pytest.mark.django_db
def test_test_center_action_run_ledger_history_filter_and_detail(settings, tmp_path):
    artifact_dir = Path(tmp_path)
    write_action_run(
        artifact_dir,
        "frontend-build-fail",
        {
            "status": "fail",
            "mode": "dry_run",
            "action_id": "action-frontend-1",
            "issue_id": "issue-frontend-1",
            "operation": "rerun_quality_suite",
            "platform": "frontend-next",
            "category": "quality",
            "generated_at": "2026-05-17T10:00:00Z",
            "started_at": "2026-05-17T10:00:01Z",
            "finished_at": "2026-05-17T10:00:09Z",
            "duration_seconds": 8.4,
            "actor": {
                "kind": "operator",
                "id": "ops@example.com",
                "label": "Ops",
            },
            "command": "pnpm build",
            "cwd": "edilcloud-next",
            "returncode": 1,
            "summary": "TypeScript build failed.",
            "stdout_tail": "build output",
            "stderr_tail": "Type error",
            "evidence": ["Build non conclusa."],
            "next_step": "Correggere il tipo segnalato e ripetere il dry-run.",
            "audit": {
                "will_modify_code": False,
                "will_touch_production": False,
                "approval_required": True,
                "approved_by": None,
            },
        },
    )
    write_action_run(
        artifact_dir,
        "backend-ruff-pass",
        {
            "status": "pass",
            "mode": "dry_run",
            "action_id": "action-backend-1",
            "issue_id": "issue-backend-1",
            "operation": "rerun_quality_suite",
            "platform": "backend",
            "category": "quality",
            "generated_at": "2026-05-17T10:05:00Z",
            "command": r"..\venv\Scripts\ruff.exe check src scripts tests",
            "returncode": 0,
            "summary": "Ruff passed.",
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.runs@example.com",
        password="devpass123",
        username="ops-runs",
    )
    client = Client()
    headers = auth_headers(client, email="ops.runs@example.com", password="devpass123")

    history_response = client.get("/api/v1/test-center/runs", **headers)

    assert history_response.status_code == 200
    history = history_response.json()
    assert history["status"] == "ok"
    assert history["count"] == 2

    filtered_response = client.get(
        "/api/v1/test-center/runs?action_id=action-frontend-1&status=fail",
        **headers,
    )

    assert filtered_response.status_code == 200
    filtered = filtered_response.json()
    assert filtered["count"] == 1
    assert filtered["filters"] == {
        "action_id": "action-frontend-1",
        "status": "fail",
    }
    run = filtered["runs"][0]
    assert run["platform"] == "frontend-next"
    assert run["stderr_tail"] == "Type error"

    detail_response = client.get(f"/api/v1/test-center/runs/{run['id']}", **headers)

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["command"] == "pnpm build"
    assert detail["actor"]["label"] == "Ops"
    assert detail["next_step"] == "Correggere il tipo segnalato e ripetere il dry-run."
    assert detail["audit"]["will_modify_code"] is False

    missing_response = client.get("/api/v1/test-center/runs/missing", **headers)
    assert missing_response.status_code == 404


@pytest.mark.django_db
def test_test_center_can_prepare_action_run_from_action_plan(settings, tmp_path):
    artifact_dir = Path(tmp_path)
    write_quality_report(
        artifact_dir,
        "frontend-warning",
        {
            "engine": "quality-suite",
            "status": "warning",
            "generated_at": "2026-05-17T11:00:00Z",
            "platform": "frontend-next",
            "suite": "quality",
            "summary": {"commands": 2, "passed": 1, "failed": 0, "skipped": 1},
            "commands": [
                {
                    "key": "frontend-eslint",
                    "label": "Frontend ESLint",
                    "status": "pass",
                    "command": "pnpm exec eslint",
                },
                {
                    "key": "frontend-build",
                    "label": "Frontend build",
                    "status": "skipped",
                    "command": "pnpm build",
                },
            ],
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.prepare@example.com",
        password="devpass123",
        username="ops-prepare",
    )
    client = Client()
    headers = auth_headers(client, email="ops.prepare@example.com", password="devpass123")

    actions_response = client.get("/api/v1/test-center/actions", **headers)
    assert actions_response.status_code == 200
    action = next(
        item
        for item in actions_response.json()["actions"]
        if item["platform"] == "frontend-next" and item["category"] == "quality"
    )
    assert action["state"] == "ready_for_dry_run"

    response = client.post(
        f"/api/v1/test-center/actions/{action['id']}/runs/plan",
        data=json.dumps(
            {
                "operation": "rerun_quality_suite",
                "note": "Verifica dal centro operativo.",
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "planned"
    assert run["mode"] == "dry_run"
    assert run["action_id"] == action["id"]
    assert run["issue_id"] == action["issue_id"]
    assert run["operation"] == "rerun_quality_suite"
    assert run["platform"] == "frontend-next"
    assert "scripts/run_quality_suite.py" in run["command"]
    assert "--suite frontend-next" in run["command"]
    assert run["actor"]["label"] == "ops.prepare@example.com"
    assert run["audit"]["will_modify_code"] is False
    assert run["audit"]["will_touch_production"] is False

    history_response = client.get(
        f"/api/v1/test-center/runs?action_id={action['id']}",
        **headers,
    )
    assert history_response.status_code == 200
    history = history_response.json()
    assert history["count"] == 1
    assert history["runs"][0]["id"] == run["id"]


@pytest.mark.django_db
def test_test_center_rejects_unallowed_action_run_operation(settings, tmp_path):
    artifact_dir = Path(tmp_path)
    write_quality_report(
        artifact_dir,
        "frontend-warning",
        {
            "engine": "quality-suite",
            "status": "warning",
            "generated_at": "2026-05-17T11:00:00Z",
            "platform": "frontend-next",
            "suite": "quality",
            "summary": {"commands": 1, "passed": 0, "failed": 0, "skipped": 1},
            "commands": [
                {
                    "key": "frontend-build",
                    "label": "Frontend build",
                    "status": "skipped",
                    "command": "pnpm build",
                }
            ],
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.prepare.invalid@example.com",
        password="devpass123",
        username="ops-prepare-invalid",
    )
    client = Client()
    headers = auth_headers(
        client,
        email="ops.prepare.invalid@example.com",
        password="devpass123",
    )
    actions_response = client.get("/api/v1/test-center/actions", **headers)
    action = next(
        item
        for item in actions_response.json()["actions"]
        if item["platform"] == "frontend-next" and item["category"] == "quality"
    )

    response = client.post(
        f"/api/v1/test-center/actions/{action['id']}/runs/plan",
        data=json.dumps({"operation": "rerun_loadtest_suite"}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400
    assert "non consentita" in response.json()["detail"]


@pytest.mark.django_db
def test_test_center_loadtest_history_and_detail(settings, tmp_path):
    artifact_dir = Path(tmp_path)
    write_locust_report(
        artifact_dir,
        "run-read",
        {
            "engine": "locust",
            "status": "pass",
            "generated_at": "2026-05-17T09:00:00Z",
            "profile": "read-heavy",
            "users": 8,
            "duration_seconds": 60.0,
            "overall": {
                "requests": 120,
                "failures": 0,
                "failure_ratio": 0.0,
                "p95_ms": 380.0,
                "p99_ms": 520.0,
            },
        },
    )
    write_locust_report(
        artifact_dir,
        "run-mixed",
        {
            "engine": "locust",
            "status": "fail",
            "generated_at": "2026-05-17T10:00:00Z",
            "host": "https://test.edilcloud.eu",
            "profile": "mixed-crud",
            "shape": "spike",
            "users": 20,
            "duration_seconds": 180.0,
            "scenario": {
                "email_prefix": "loadtest.user",
                "project_id": 42,
                "search_terms": ["task", "documento"],
            },
            "thresholds": {"max_failure_ratio": 0.01, "max_p95_ms": 1200},
            "overall": {
                "requests": 400,
                "failures": 8,
                "failure_ratio": 0.02,
                "p95_ms": 1400.0,
                "p99_ms": 1900.0,
            },
            "endpoints": [
                {
                    "method": "POST",
                    "name": "posts.create",
                    "requests": 60,
                    "failures": 3,
                    "p95_ms": 1450,
                }
            ],
            "failures": [
                {
                    "method": "POST",
                    "name": "posts.create",
                    "error": "HTTP 500",
                }
            ],
            "process": {
                "returncode": 1,
                "stdout_tail": "summary",
                "stderr_tail": "trace tail",
            },
        },
    )
    settings.TEST_CENTER_ARTIFACT_DIR = str(artifact_dir)
    get_user_model().objects.create_superuser(
        email="ops.history@example.com",
        password="devpass123",
        username="ops-history",
    )
    client = Client()
    headers = auth_headers(client, email="ops.history@example.com", password="devpass123")

    history_response = client.get("/api/v1/test-center/loadtests", **headers)

    assert history_response.status_code == 200
    history = history_response.json()
    assert history["status"] == "ok"
    assert history["count"] == 2
    reports = {item["profile"]: item for item in history["reports"]}
    assert reports["mixed-crud"]["summary"]["failures"] == 8

    detail_response = client.get(
        f"/api/v1/test-center/loadtests/{reports['mixed-crud']['id']}",
        **headers,
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["host"] == "https://test.edilcloud.eu"
    assert detail["shape"] == "spike"
    assert detail["scenario"]["project_id"] == 42
    assert detail["endpoints"][0]["name"] == "posts.create"
    assert detail["failures"][0]["error"] == "HTTP 500"
    assert detail["process"]["stderr_tail"] == "trace tail"


@pytest.mark.django_db
def test_test_center_platform_detail_supports_backend_and_rejects_unknown_platform():
    get_user_model().objects.create_superuser(
        email="ops.platform@example.com",
        password="devpass123",
        username="ops-platform",
    )
    client = Client()
    headers = auth_headers(client, email="ops.platform@example.com", password="devpass123")

    backend_response = client.get("/api/v1/test-center/platforms/backend", **headers)
    assert backend_response.status_code == 200
    backend_payload = backend_response.json()
    assert backend_payload["platform"]["key"] == "backend"
    assert backend_payload["performance"] is not None
    assert backend_payload["loadtests"] is not None
    assert backend_payload["quality"] is not None

    missing_response = client.get("/api/v1/test-center/platforms/unknown", **headers)
    assert missing_response.status_code == 404
