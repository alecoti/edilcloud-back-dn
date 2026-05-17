from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from django.conf import settings

from edilcloud.platform.api.health import build_health_payload
from edilcloud.platform.performance_budget import evaluate_runtime_summary
from edilcloud.platform.telemetry import metrics_summary
from edilcloud.platform.test_center_artifacts import (
    load_latest_loadtest_report,
    load_latest_quality_reports,
)


TEST_CENTER_PLATFORM_KEYS = {"backend", "frontend-next", "flutter"}


def _now_isoformat() -> str:
    timezone_name = getattr(settings, "TIME_ZONE", "UTC")
    return datetime.now(ZoneInfo(timezone_name)).isoformat()


def _backend_status(
    health: dict[str, str],
    budget: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    http_totals = summary.get("http", {}).get("totals", {})
    error_ratio = float(http_totals.get("error_ratio") or 0.0)

    if health.get("cache") == "error":
        return "critical"
    if budget.get("status") == "fail" or error_ratio >= 0.05:
        return "critical"
    if health.get("cache") == "degraded" or budget.get("status") in {"partial", "no_data"}:
        return "warning"
    return "ok"


def _backend_focus(
    health: dict[str, str],
    budget: dict[str, Any],
    summary: dict[str, Any],
) -> list[str]:
    focus: list[str] = []
    if health.get("cache") != "ok":
        focus.append(f"Cache backend in stato {health.get('cache', 'unknown')}.")
    for item in budget.get("failing", []):
        if not isinstance(item, dict):
            continue
        focus.append(
            "Budget fuori soglia su {key}: p95 {p95_ms} ms su limite {max_p95_ms} ms.".format(
                key=item.get("key", "-"),
                p95_ms=item.get("p95_ms", 0),
                max_p95_ms=item.get("max_p95_ms", 0),
            )
        )
    hot_paths = summary.get("http", {}).get("top_slowest", [])
    for item in hot_paths:
        if not isinstance(item, dict) or item.get("performance_status") == "ok":
            continue
        focus.append(
            "Hot path {method} {path}: p95 {p95_ms} ms.".format(
                method=item.get("method", "GET"),
                path=item.get("path", "/"),
                p95_ms=item.get("p95_ms", 0),
            )
        )
    return focus[:5]


def _quality_platform_status(report: dict[str, Any]) -> str:
    status = report.get("status")
    if status == "pass":
        return "ok"
    if status == "fail":
        return "critical"
    if status in {"warning", "skipped"}:
        return "warning"
    return "no_data"


def _quality_check_status(report: dict[str, Any]) -> str:
    status = _quality_platform_status(report)
    return "warning" if status == "no_data" else status


def _merge_status(*statuses: str) -> str:
    if any(status == "critical" for status in statuses):
        return "critical"
    if any(status == "warning" for status in statuses):
        return "warning"
    if statuses and all(status == "no_data" for status in statuses):
        return "no_data"
    if any(status == "no_data" for status in statuses):
        return "warning"
    return "ok"


def _quality_detail(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    return (
        "{passed}/{commands} comandi passati, {failed} falliti, {skipped} saltati.".format(
            passed=summary.get("passed", 0),
            commands=summary.get("commands", 0),
            failed=summary.get("failed", 0),
            skipped=summary.get("skipped", 0),
        )
    )


def build_test_center_overview() -> dict[str, Any]:
    health = build_health_payload()
    runtime_summary = metrics_summary()
    runtime_budget = evaluate_runtime_summary(runtime_summary)
    loadtest_report = load_latest_loadtest_report()
    quality_reports = load_latest_quality_reports()
    backend_quality = quality_reports["backend"]
    frontend_quality = quality_reports["frontend-next"]
    flutter_quality = quality_reports["flutter"]
    backend_runtime_status = _backend_status(health, runtime_budget, runtime_summary)
    backend_status = _merge_status(
        backend_runtime_status,
        _quality_platform_status(backend_quality),
    )
    http_summary = runtime_summary.get("http", {})
    http_totals = http_summary.get("totals", {})

    backend_platform = {
        "key": "backend",
        "label": "Backend",
        "status": backend_status,
        "data_state": "live",
        "summary": "Healthcheck, cache, runtime telemetry e budget prestazionali backend.",
        "last_seen_at": health["now"],
        "checks": [
            {
                "key": "health",
                "label": "Healthcheck",
                "status": "ok" if health.get("status") == "ok" else "critical",
                "detail": f"Servizio {health.get('service')} in ambiente {health.get('environment')}.",
            },
            {
                "key": "cache",
                "label": "Cache",
                "status": "ok" if health.get("cache") == "ok" else "warning",
                "detail": f"Cache {health.get('cache', 'unknown')}.",
            },
            {
                "key": "runtime-budget",
                "label": "Runtime budget",
                "status": (
                    "ok"
                    if runtime_budget.get("status") == "pass"
                    else "critical"
                    if runtime_budget.get("status") == "fail"
                    else "warning"
                ),
                "detail": (
                    "{passing}/{checked} regole passate, {failing} fuori soglia, {missing} senza dati.".format(
                        passing=runtime_budget.get("passing_rules", 0),
                        checked=runtime_budget.get("checked_rules", 0),
                        failing=runtime_budget.get("failing_rules", 0),
                        missing=runtime_budget.get("no_data_rules", 0),
                    )
                ),
            },
            {
                "key": "quality-suite",
                "label": "Quality suite",
                "status": _quality_check_status(backend_quality),
                "detail": _quality_detail(backend_quality),
            },
            {
                "key": "loadtests",
                "label": "Load test",
                "status": (
                    "ok"
                    if loadtest_report.get("status") == "pass"
                    else "critical"
                    if loadtest_report.get("status") == "fail"
                    else "warning"
                ),
                "detail": (
                    "Ultimo report {engine}/{profile}: {requests} richieste, p95 {p95_ms} ms.".format(
                        engine=loadtest_report.get("engine", "locust"),
                        profile=loadtest_report.get("profile") or "n/a",
                        requests=loadtest_report.get("summary", {}).get("requests", 0),
                        p95_ms=loadtest_report.get("summary", {}).get("p95_ms", 0),
                    )
                ),
            },
        ],
        "targets": [],
        "focus": [
            *_backend_focus(health, runtime_budget, runtime_summary),
            *backend_quality.get("focus", []),
        ],
    }

    frontend_status = _quality_platform_status(frontend_quality)
    frontend_platform = {
        "key": "frontend-next",
        "label": "Frontend Next",
        "status": frontend_status,
        "data_state": (
            "live"
            if frontend_quality.get("data_state") == "live"
            else "pending_instrumentation"
        ),
        "summary": "Web vitals, route tests, browser errors e synthetic checks frontend.",
        "last_seen_at": frontend_quality.get("generated_at"),
        "checks": [
            {
                "key": "quality-suite",
                "label": "Quality suite",
                "status": _quality_check_status(frontend_quality),
                "detail": _quality_detail(frontend_quality),
            }
        ],
        "targets": [],
        "focus": frontend_quality.get("focus", []),
    }

    flutter_android = flutter_quality["android"]
    flutter_ios = flutter_quality["ios"]
    flutter_status = _merge_status(
        _quality_platform_status(flutter_android),
        _quality_platform_status(flutter_ios),
    )
    flutter_platform = {
        "key": "flutter",
        "label": "Flutter",
        "status": flutter_status,
        "data_state": (
            "live"
            if flutter_android.get("data_state") == "live"
            or flutter_ios.get("data_state") == "live"
            else "pending_instrumentation"
        ),
        "summary": "Telemetria app condivisa con dettaglio separato Android e iOS.",
        "last_seen_at": flutter_android.get("generated_at") or flutter_ios.get("generated_at"),
        "checks": [
            {
                "key": "quality-android",
                "label": "Android quality",
                "status": _quality_check_status(flutter_android),
                "detail": _quality_detail(flutter_android),
            },
            {
                "key": "quality-ios",
                "label": "iOS quality",
                "status": _quality_check_status(flutter_ios),
                "detail": _quality_detail(flutter_ios),
            },
        ],
        "targets": [
            {
                "key": "android",
                "label": "Android",
                "status": _quality_platform_status(flutter_android),
            },
            {
                "key": "ios",
                "label": "iOS",
                "status": _quality_platform_status(flutter_ios),
            },
        ],
        "focus": [
            *flutter_android.get("focus", []),
            *flutter_ios.get("focus", []),
        ][:6],
    }
    platforms = [backend_platform, frontend_platform, flutter_platform]

    if backend_status == "critical":
        overall_status = "critical"
    elif backend_status == "warning" or any(
        platform["status"] == "no_data" for platform in platforms
    ):
        overall_status = "warning"
    else:
        overall_status = "ok"

    recommendations = list(backend_platform["focus"])
    if frontend_platform["status"] == "no_data":
        recommendations.append("Collegare metriche e synthetic checks del frontend Next.")
    elif frontend_platform["status"] == "critical":
        recommendations.extend(frontend_quality.get("focus", []))
    if flutter_platform["status"] == "no_data":
        recommendations.append("Collegare telemetria Flutter separata per Android e iOS.")
    elif flutter_platform["status"] == "critical":
        recommendations.extend(flutter_platform["focus"])
    if loadtest_report["status"] == "no_data":
        recommendations.append("Eseguire una suite Locust e pubblicare il report normalizzato.")
    elif loadtest_report["status"] == "fail":
        recommendations.extend(loadtest_report.get("focus", []))

    return {
        "generated_at": _now_isoformat(),
        "overall_status": overall_status,
        "summary": {
            "platform_count": len(platforms),
            "live_platforms": sum(platform["data_state"] == "live" for platform in platforms),
            "attention_platforms": sum(platform["status"] != "ok" for platform in platforms),
            "runtime_rules_checked": int(runtime_budget.get("checked_rules") or 0),
            "runtime_rules_failing": int(runtime_budget.get("failing_rules") or 0),
            "latest_loadtest_status": loadtest_report["status"],
            "latest_quality_status": {
                "backend": backend_quality["status"],
                "frontend-next": frontend_quality["status"],
                "flutter_android": flutter_android["status"],
                "flutter_ios": flutter_ios["status"],
            },
        },
        "platforms": platforms,
        "performance": {
            "runtime_budget": runtime_budget,
            "http_totals": http_totals,
            "top_slowest": http_summary.get("top_slowest", []),
            "top_errors": http_summary.get("top_errors", []),
            "hot_paths": http_summary.get("hot_paths", []),
        },
        "loadtests": loadtest_report,
        "quality": quality_reports,
        "recommendations": recommendations[:8],
    }


def build_test_center_platform_detail(platform_key: str) -> dict[str, Any] | None:
    if platform_key not in TEST_CENTER_PLATFORM_KEYS:
        return None
    overview = build_test_center_overview()
    platform = next(
        (item for item in overview["platforms"] if item["key"] == platform_key),
        None,
    )
    if not isinstance(platform, dict):
        return None
    return {
        "generated_at": overview["generated_at"],
        "overall_status": overview["overall_status"],
        "platform": platform,
        "performance": overview["performance"] if platform_key == "backend" else None,
        "loadtests": overview["loadtests"] if platform_key == "backend" else None,
        "quality": (
            overview["quality"].get(platform_key)
            if platform_key != "flutter"
            else overview["quality"]["flutter"]
        ),
    }
