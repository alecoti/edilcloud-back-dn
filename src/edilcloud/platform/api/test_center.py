from __future__ import annotations

from typing import Any

from django.conf import settings
from ninja import Router, Schema
from ninja.errors import HttpError

from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.platform.test_center import (
    build_test_center_overview,
    build_test_center_platform_detail,
)
from edilcloud.platform.test_center_actions import (
    build_test_center_action_detail,
    build_test_center_actions,
)
from edilcloud.platform.test_center_action_runs import (
    TestCenterActionRunError,
    launch_action_run,
    prepare_action_run,
)
from edilcloud.platform.test_center_catalog import (
    build_test_center_catalog,
    ingest_quality_report,
    launch_catalog_suite,
)
from edilcloud.platform.test_center_artifacts import (
    load_loadtest_history,
    load_loadtest_report_by_id,
    load_quality_history,
    load_quality_report_by_id,
)
from edilcloud.platform.test_center_issues import build_test_center_issues
from edilcloud.platform.test_center_run_ledger import (
    load_action_run_by_id,
    load_action_run_history,
)


auth = JWTAuth()
router = Router(tags=["test-center"])


class TestCenterOverviewResponse(Schema):
    generated_at: str
    overall_status: str
    summary: dict[str, Any]
    platforms: list[dict[str, Any]]
    performance: dict[str, Any]
    loadtests: dict[str, Any]
    quality: dict[str, Any]
    recommendations: list[str]


class TestCenterPlatformResponse(Schema):
    generated_at: str
    overall_status: str
    platform: dict[str, Any]
    performance: dict[str, Any] | None
    loadtests: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None


class TestCenterIssuesResponse(Schema):
    generated_at: str
    status: str
    summary: dict[str, Any]
    issues: list[dict[str, Any]]
    recently_resolved: list[dict[str, Any]]


class TestCenterActionsResponse(Schema):
    generated_at: str
    status: str
    summary: dict[str, Any]
    actions: list[dict[str, Any]]


class TestCenterActionResponse(Schema):
    id: str
    issue_id: str
    state: str
    mode: str
    risk: str
    platform: str
    target: str | None = None
    category: str
    title: str
    objective: str
    source_issue: dict[str, Any]
    preconditions: list[str]
    plan: list[dict[str, Any]]
    allowed_operations: list[str]
    verification_commands: list[str]
    blocked_by: list[str]
    success_criteria: list[str]
    audit: dict[str, Any]


class TestCenterActionRunHistoryResponse(Schema):
    generated_at: str
    status: str
    count: int
    filters: dict[str, Any]
    runs: list[dict[str, Any]]


class TestCenterActionRunResponse(Schema):
    id: str
    status: str
    mode: str
    action_id: str
    issue_id: str | None = None
    operation: str
    platform: str
    target: str | None = None
    category: str
    generated_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    duration_seconds: float
    actor: dict[str, Any]
    command: str
    cwd: str
    returncode: int | None = None
    summary: str
    stdout_tail: str
    stderr_tail: str
    artifacts: dict[str, str]
    source_path: str
    evidence: list[str]
    next_step: str
    audit: dict[str, Any]


class TestCenterPrepareActionRunRequest(Schema):
    operation: str
    approved_by: str | None = None
    note: str = ""
    loadtest_profile: str = "read-heavy"
    loadtest_host: str = "http://localhost:3000"
    loadtest_users: int = 10
    loadtest_spawn_rate: float = 5.0
    loadtest_run_time: str = "2m"


class TestCenterLoadtestHistoryResponse(Schema):
    generated_at: str
    status: str
    count: int
    reports: list[dict[str, Any]]


class TestCenterCatalogResponse(Schema):
    generated_at: str
    status: str
    summary: dict[str, Any]
    suites: list[dict[str, Any]]


class TestCenterLaunchCatalogSuiteRequest(Schema):
    approved_by: str | None = None
    loadtest_host: str = "http://localhost:3000"
    loadtest_users: int = 10
    loadtest_spawn_rate: float = 5.0
    loadtest_run_time: str = "2m"


class TestCenterIngestResponse(Schema):
    status: str
    source_path: str


class TestCenterQualityIngestRequest(Schema):
    engine: str
    status: str
    generated_at: str | None = None
    platform: str
    target: str | None = None
    suite: str
    summary: dict[str, Any]
    commands: list[dict[str, Any]]
    focus: list[str] = []


class TestCenterLoadtestReportResponse(Schema):
    id: str
    status: str
    data_state: str
    engine: str
    profile: str
    generated_at: str | None
    source_path: str
    summary: dict[str, Any]
    artifacts: dict[str, str]
    focus: list[str]
    host: str | None = None
    shape: str | None = None
    thresholds: dict[str, Any] | None = None
    scenario: dict[str, Any] | None = None
    endpoints: list[dict[str, Any]] | None = None
    failures: list[dict[str, Any]] | None = None
    stages: list[dict[str, Any]] | None = None
    process: dict[str, Any] | None = None


class TestCenterQualityHistoryResponse(Schema):
    generated_at: str
    status: str
    count: int
    filters: dict[str, Any]
    reports: list[dict[str, Any]]


class TestCenterQualityReportResponse(Schema):
    id: str
    status: str
    data_state: str
    engine: str
    platform: str
    target: str | None = None
    suite: str
    generated_at: str | None
    source_path: str
    summary: dict[str, Any]
    commands: list[dict[str, Any]]
    focus: list[str]


def require_superuser(request) -> None:
    if not getattr(request.auth.user, "is_superuser", False):
        raise HttpError(403, "Area riservata ai superuser.")


@router.get("/overview", response=TestCenterOverviewResponse, auth=auth)
def get_test_center_overview(request):
    require_superuser(request)
    return build_test_center_overview()


@router.get("/issues", response=TestCenterIssuesResponse, auth=auth)
def get_test_center_issues(request):
    require_superuser(request)
    return build_test_center_issues()


@router.get("/actions", response=TestCenterActionsResponse, auth=auth)
def get_test_center_actions(request):
    require_superuser(request)
    return build_test_center_actions()


@router.get("/actions/{action_id}", response=TestCenterActionResponse, auth=auth)
def get_test_center_action(request, action_id: str):
    require_superuser(request)
    action = build_test_center_action_detail(action_id)
    if action is None:
        raise HttpError(404, "Azione Test Center non trovata.")
    return action


@router.post(
    "/actions/{action_id}/runs/plan",
    response=TestCenterActionRunResponse,
    auth=auth,
)
def prepare_test_center_action_run(
    request,
    action_id: str,
    payload: TestCenterPrepareActionRunRequest,
):
    require_superuser(request)
    user = request.auth.user
    actor_label = getattr(user, "email", "") or getattr(user, "username", "") or str(user.pk)
    try:
        return prepare_action_run(
            action_id=action_id,
            operation=payload.operation,
            actor_id=str(user.pk),
            actor_label=actor_label,
            approved_by=payload.approved_by,
            note=payload.note,
            loadtest_profile=payload.loadtest_profile,
            loadtest_host=payload.loadtest_host,
            loadtest_users=payload.loadtest_users,
            loadtest_spawn_rate=payload.loadtest_spawn_rate,
            loadtest_run_time=payload.loadtest_run_time,
        )
    except TestCenterActionRunError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post(
    "/actions/{action_id}/runs/launch",
    response=TestCenterActionRunResponse,
    auth=auth,
)
def launch_test_center_action_run(
    request,
    action_id: str,
    payload: TestCenterPrepareActionRunRequest,
):
    require_superuser(request)
    user = request.auth.user
    actor_label = getattr(user, "email", "") or getattr(user, "username", "") or str(user.pk)
    try:
        return launch_action_run(
            action_id=action_id,
            operation=payload.operation,
            actor_id=str(user.pk),
            actor_label=actor_label,
            approved_by=payload.approved_by,
            note=payload.note,
            loadtest_profile=payload.loadtest_profile,
            loadtest_host=payload.loadtest_host,
            loadtest_users=payload.loadtest_users,
            loadtest_spawn_rate=payload.loadtest_spawn_rate,
            loadtest_run_time=payload.loadtest_run_time,
        )
    except TestCenterActionRunError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/runs", response=TestCenterActionRunHistoryResponse, auth=auth)
def get_test_center_action_runs(
    request,
    action_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
):
    require_superuser(request)
    return load_action_run_history(limit=limit, action_id=action_id, status=status)


@router.get("/runs/{run_id}", response=TestCenterActionRunResponse, auth=auth)
def get_test_center_action_run(request, run_id: str):
    require_superuser(request)
    run = load_action_run_by_id(run_id)
    if run is None:
        raise HttpError(404, "Run Test Center non trovato.")
    return run


@router.get("/loadtests", response=TestCenterLoadtestHistoryResponse, auth=auth)
def get_test_center_loadtests(request):
    require_superuser(request)
    return load_loadtest_history()


@router.get("/catalog", response=TestCenterCatalogResponse, auth=auth)
def get_test_center_catalog(request):
    require_superuser(request)
    return build_test_center_catalog()


@router.post(
    "/catalog/{suite_id}/runs/launch",
    response=TestCenterActionRunResponse,
    auth=auth,
)
def launch_test_center_catalog_suite(
    request,
    suite_id: str,
    payload: TestCenterLaunchCatalogSuiteRequest,
):
    require_superuser(request)
    user = request.auth.user
    actor_label = getattr(user, "email", "") or getattr(user, "username", "") or str(user.pk)
    try:
        return launch_catalog_suite(
            suite_id=suite_id,
            actor_id=str(user.pk),
            actor_label=actor_label,
            approved_by=payload.approved_by,
            loadtest_host=payload.loadtest_host,
            loadtest_users=payload.loadtest_users,
            loadtest_spawn_rate=payload.loadtest_spawn_rate,
            loadtest_run_time=payload.loadtest_run_time,
        )
    except TestCenterActionRunError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/ingest/quality", response=TestCenterIngestResponse)
def ingest_test_center_quality_report(request, payload: TestCenterQualityIngestRequest):
    configured = str(getattr(settings, "TEST_CENTER_INGEST_TOKEN", "") or "")
    provided = request.headers.get("X-Test-Center-Ingest-Token", "")
    if not configured or provided != configured:
        raise HttpError(403, "Token ingest Test Center non valido.")
    try:
        artifact_path = ingest_quality_report(
            payload.dict(),
            run_name=request.headers.get("X-Test-Center-Run-Name") or None,
        )
    except TestCenterActionRunError as exc:
        raise HttpError(400, str(exc)) from exc
    return {"status": "accepted", "source_path": str(artifact_path)}


@router.get("/loadtests/{run_id}", response=TestCenterLoadtestReportResponse, auth=auth)
def get_test_center_loadtest_report(request, run_id: str):
    require_superuser(request)
    report = load_loadtest_report_by_id(run_id)
    if report is None:
        raise HttpError(404, "Report load test non trovato.")
    return report


@router.get("/quality", response=TestCenterQualityHistoryResponse, auth=auth)
def get_test_center_quality_history(
    request,
    platform: str | None = None,
    target: str | None = None,
    limit: int = 25,
):
    require_superuser(request)
    return load_quality_history(limit=limit, platform=platform, target=target)


@router.get("/quality/{run_id}", response=TestCenterQualityReportResponse, auth=auth)
def get_test_center_quality_report(request, run_id: str):
    require_superuser(request)
    report = load_quality_report_by_id(run_id)
    if report is None:
        raise HttpError(404, "Report quality non trovato.")
    return report


@router.get("/platforms/{platform_key}", response=TestCenterPlatformResponse, auth=auth)
def get_test_center_platform_detail(request, platform_key: str):
    require_superuser(request)
    platform = build_test_center_platform_detail(platform_key)
    if platform is None:
        raise HttpError(404, "Piattaforma Test Center non trovata.")
    return platform
