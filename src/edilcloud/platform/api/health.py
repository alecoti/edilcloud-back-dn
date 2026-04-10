from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache
from ninja import Router, Schema
from ninja.errors import HttpError

from edilcloud.platform.performance_budget import evaluate_runtime_summary
from edilcloud.platform.telemetry import metrics_snapshot, metrics_summary, reset_metrics


class HealthResponse(Schema):
    status: str
    service: str
    version: str
    environment: str
    timezone: str
    now: str
    cache: str
    realtime: str
    log_format: str
    log_level: str
    sentry: str
    openai: str
    vector_store: str


class MetricsResponse(Schema):
    status: str
    metrics: dict


class MetricsSummaryResponse(Schema):
    status: str
    summary: dict


class MetricsBudgetResponse(Schema):
    status: str
    budget: dict


class MetricsResetResponse(Schema):
    status: str
    reset: bool


router = Router(tags=["health"])


@router.get("", response=HealthResponse)
def healthcheck(request):
    timezone_name = getattr(settings, "TIME_ZONE", "UTC")
    now = datetime.now(ZoneInfo(timezone_name))
    cache_status = "ok"
    try:
        cache_key = "healthcheck"
        cache.set(cache_key, "ok", timeout=5)
        if cache.get(cache_key) != "ok":
            cache_status = "degraded"
    except Exception:
        cache_status = "error"

    realtime_status = "ok" if getattr(settings, "CHANNEL_LAYERS", None) else "disabled"
    return HealthResponse(
        status="ok",
        service="edilcloud-back-dn",
        version=getattr(settings, "APP_VERSION", "0.1.0-dev"),
        environment=getattr(settings, "APP_ENV", "local"),
        timezone=timezone_name,
        now=now.isoformat(),
        cache=cache_status,
        realtime=realtime_status,
        log_format=getattr(settings, "LOG_FORMAT", "console"),
        log_level=getattr(settings, "LOG_LEVEL", "INFO"),
        sentry="configured" if getattr(settings, "SENTRY_DSN", "") else "disabled",
        openai="configured" if getattr(settings, "OPENAI_API_KEY", "") else "disabled",
        vector_store="pgvector" if getattr(settings, "OPENAI_API_KEY", "") else "disabled",
    )


@router.get("/metrics", response=MetricsResponse)
def metrics(request):
    return MetricsResponse(
        status="ok",
        metrics=metrics_snapshot(),
    )


@router.get("/metrics/summary", response=MetricsSummaryResponse)
def metrics_summary_view(request):
    return MetricsSummaryResponse(
        status="ok",
        summary=metrics_summary(),
    )


@router.get("/metrics/budget", response=MetricsBudgetResponse)
def metrics_budget_view(request):
    summary = metrics_summary()
    return MetricsBudgetResponse(
        status="ok",
        budget=evaluate_runtime_summary(summary),
    )


@router.post("/metrics/reset", response=MetricsResetResponse)
def metrics_reset_view(request):
    app_env = str(getattr(settings, "APP_ENV", "local")).lower()
    if not bool(getattr(settings, "DEBUG", False)) and app_env not in {"local", "dev", "test"}:
        raise HttpError(403, "Reset metriche disponibile solo in dev.")
    reset_metrics()
    return MetricsResetResponse(status="ok", reset=True)
