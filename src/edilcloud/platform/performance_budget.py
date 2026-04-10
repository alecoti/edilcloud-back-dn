from __future__ import annotations

from dataclasses import dataclass
from math import floor
import re
from typing import Any


@dataclass(frozen=True)
class PerformanceBudgetRule:
    key: str
    method: str
    path_pattern: str
    max_p95_ms: float
    max_error_ratio: float = 0.01
    min_requests: int = 1


DEV_PERFORMANCE_BUDGETS: tuple[PerformanceBudgetRule, ...] = (
    PerformanceBudgetRule(
        key="health",
        method="GET",
        path_pattern=r"^/api/v1/health$",
        max_p95_ms=1500.0,
        max_error_ratio=0.0,
    ),
    PerformanceBudgetRule(
        key="auth.login",
        method="POST",
        path_pattern=r"^/api/v1/auth/login$",
        max_p95_ms=900.0,
        max_error_ratio=0.01,
    ),
    PerformanceBudgetRule(
        key="projects.list",
        method="GET",
        path_pattern=r"^/api/v1/projects$",
        max_p95_ms=900.0,
    ),
    PerformanceBudgetRule(
        key="projects.feed",
        method="GET",
        path_pattern=r"^/api/v1/projects/feed$",
        max_p95_ms=1000.0,
    ),
    PerformanceBudgetRule(
        key="projects.overview",
        method="GET",
        path_pattern=r"^/api/v1/projects/\d+/overview$",
        max_p95_ms=1200.0,
    ),
    PerformanceBudgetRule(
        key="projects.tasks",
        method="GET",
        path_pattern=r"^/api/v1/projects/\d+/tasks$",
        max_p95_ms=1200.0,
    ),
    PerformanceBudgetRule(
        key="projects.gantt",
        method="GET",
        path_pattern=r"^/api/v1/projects/\d+/gantt$",
        max_p95_ms=1500.0,
    ),
    PerformanceBudgetRule(
        key="projects.documents",
        method="GET",
        path_pattern=r"^/api/v1/projects/\d+/documents$",
        max_p95_ms=1200.0,
    ),
    PerformanceBudgetRule(
        key="search.global",
        method="GET",
        path_pattern=r"^/api/v1/search/global$",
        max_p95_ms=900.0,
    ),
    PerformanceBudgetRule(
        key="notifications.list",
        method="GET",
        path_pattern=r"^/api/v1/notifications$",
        max_p95_ms=900.0,
    ),
    PerformanceBudgetRule(
        key="assistant.state",
        method="GET",
        path_pattern=r"^/api/v1/projects/\d+/assistant$",
        max_p95_ms=1500.0,
    ),
)


def _rule_score(*, passing: int, total: int) -> int:
    if total <= 0:
        return 0
    return floor((passing / total) * 100)


def evaluate_runtime_summary(
    summary: dict[str, Any],
    *,
    budgets: tuple[PerformanceBudgetRule, ...] = DEV_PERFORMANCE_BUDGETS,
) -> dict[str, Any]:
    http_summary = summary.get("http") if isinstance(summary, dict) else {}
    endpoints = http_summary.get("endpoints") if isinstance(http_summary, dict) else []
    endpoint_list = endpoints if isinstance(endpoints, list) else []

    rules_report: list[dict[str, Any]] = []
    passing = 0
    failing = 0
    no_data = 0

    for rule in budgets:
        matcher = re.compile(rule.path_pattern)
        matched = [
            endpoint
            for endpoint in endpoint_list
            if str(endpoint.get("method")) == rule.method and matcher.match(str(endpoint.get("path", "")))
        ]

        total_requests = sum(int(item.get("requests") or 0) for item in matched)
        weighted_errors = sum(
            float(item.get("error_ratio") or 0.0) * int(item.get("requests") or 0)
            for item in matched
        )
        error_ratio = round(weighted_errors / total_requests, 4) if total_requests else 0.0
        p95_ms = max((float(item.get("p95_ms") or 0.0) for item in matched), default=0.0)
        matched_paths = [str(item.get("path")) for item in matched]

        if total_requests < rule.min_requests:
            status = "no_data"
            no_data += 1
        elif p95_ms <= rule.max_p95_ms and error_ratio <= rule.max_error_ratio:
            status = "pass"
            passing += 1
        else:
            status = "fail"
            failing += 1

        rules_report.append(
            {
                "key": rule.key,
                "method": rule.method,
                "path_pattern": rule.path_pattern,
                "matched_paths": matched_paths,
                "requests": total_requests,
                "p95_ms": round(p95_ms, 2),
                "error_ratio": error_ratio,
                "max_p95_ms": rule.max_p95_ms,
                "max_error_ratio": rule.max_error_ratio,
                "status": status,
            }
        )

    if failing > 0:
        overall_status = "fail"
    elif passing > 0 and no_data == 0:
        overall_status = "pass"
    else:
        overall_status = "partial"

    return {
        "status": overall_status,
        "score_percent": _rule_score(passing=passing, total=len(budgets)),
        "checked_rules": len(budgets),
        "passing_rules": passing,
        "failing_rules": failing,
        "no_data_rules": no_data,
        "rules": rules_report,
        "failing": [item for item in rules_report if item["status"] == "fail"],
        "missing_data": [item for item in rules_report if item["status"] == "no_data"],
    }
