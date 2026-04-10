from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_P95_REGRESSION_RATIO = 0.15
DEFAULT_FAILURE_RATIO_DELTA = 0.005
DEFAULT_DELIVERY_RATIO_DROP = 0.01
DEFAULT_EMPTY_RATIO_DELTA = 0.2


@dataclass(frozen=True)
class ComparisonThresholds:
    max_p95_regression_ratio: float = DEFAULT_P95_REGRESSION_RATIO
    max_failure_ratio_increase: float = DEFAULT_FAILURE_RATIO_DELTA
    max_delivery_ratio_drop: float = DEFAULT_DELIVERY_RATIO_DROP
    max_empty_ratio_increase: float = DEFAULT_EMPTY_RATIO_DELTA


def build_performance_baseline_bundle(
    *,
    kind: str = "generic",
    label: str,
    generated_at: str,
    runtime_budget: dict[str, Any] | None = None,
    runtime_summary: dict[str, Any] | None = None,
    read_heavy: dict[str, Any] | None = None,
    auth_burst: dict[str, Any] | None = None,
    mixed_crud: dict[str, Any] | None = None,
    realtime: dict[str, Any] | None = None,
    search_benchmark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "kind": kind,
        "label": label,
        "generated_at": generated_at,
        "runtime_budget": runtime_budget or {},
        "runtime_summary": runtime_summary or {},
        "loadtests": {
            "read_heavy": read_heavy or {},
            "auth_burst": auth_burst or {},
            "mixed_crud": mixed_crud or {},
            "realtime": realtime or {},
        },
        "search_benchmark": search_benchmark or {},
    }


def _extract_budget(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    budget = payload.get("budget")
    return budget if isinstance(budget, dict) else payload


def _stage_index(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    stages = report.get("stages") if isinstance(report, dict) else []
    if not isinstance(stages, list):
        return {}
    indexed: dict[int, dict[str, Any]] = {}
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        try:
            indexed[int(stage["users"])] = stage
        except Exception:
            continue
    return indexed


def _compare_budget(
    baseline_payload: dict[str, Any],
    current_payload: dict[str, Any],
) -> dict[str, Any]:
    baseline = _extract_budget(baseline_payload)
    current = _extract_budget(current_payload)
    if not baseline or not current:
        return {
            "status": "no_data",
            "regressions": [],
            "baseline_score": 0,
            "current_score": 0,
        }

    regressions: list[str] = []
    baseline_score = int(baseline.get("score_percent") or 0)
    current_score = int(current.get("score_percent") or 0)
    if current_score < baseline_score:
        regressions.append(
            f"runtime budget score peggiorato da {baseline_score}% a {current_score}%"
        )

    baseline_rules = {
        str(item.get("key")): item
        for item in baseline.get("rules", [])
        if isinstance(item, dict) and item.get("key")
    }
    current_rules = {
        str(item.get("key")): item
        for item in current.get("rules", [])
        if isinstance(item, dict) and item.get("key")
    }
    for key, baseline_rule in baseline_rules.items():
        current_rule = current_rules.get(key)
        if not current_rule:
            continue
        if baseline_rule.get("status") == "pass" and current_rule.get("status") == "fail":
            regressions.append(f"runtime budget `{key}` e passato da pass a fail")

    return {
        "status": "fail" if regressions else "pass",
        "regressions": regressions,
        "baseline_score": baseline_score,
        "current_score": current_score,
    }


def _compare_http_loadtest(
    name: str,
    baseline_report: dict[str, Any],
    current_report: dict[str, Any],
    *,
    thresholds: ComparisonThresholds,
) -> dict[str, Any]:
    baseline_stages = _stage_index(baseline_report)
    current_stages = _stage_index(current_report)
    overlapping = sorted(set(baseline_stages) & set(current_stages))
    if not overlapping:
        return {"status": "no_data", "regressions": [], "compared_stages": []}

    regressions: list[str] = []
    compared_stages: list[dict[str, Any]] = []

    baseline_best_stage = max(
        (users for users, stage in baseline_stages.items() if stage.get("pass")),
        default=0,
    )
    current_best_stage = max(
        (users for users, stage in current_stages.items() if stage.get("pass")),
        default=0,
    )
    if current_best_stage < baseline_best_stage:
        regressions.append(
            f"{name} best passing stage peggiorato da {baseline_best_stage} a {current_best_stage}"
        )

    for users in overlapping:
        base = baseline_stages[users]
        curr = current_stages[users]
        base_p95 = float(base.get("p95_ms") or 0.0)
        curr_p95 = float(curr.get("p95_ms") or 0.0)
        base_failure = float(base.get("failure_ratio") or 0.0)
        curr_failure = float(curr.get("failure_ratio") or 0.0)
        p95_ratio = ((curr_p95 - base_p95) / base_p95) if base_p95 > 0 else 0.0
        failure_delta = curr_failure - base_failure
        stage_regressions: list[str] = []

        if bool(base.get("pass")) and not bool(curr.get("pass")):
            stage_regressions.append("stage passata a fail")
        if p95_ratio > thresholds.max_p95_regression_ratio:
            stage_regressions.append(
                f"p95 peggiorato oltre soglia ({round(p95_ratio * 100, 2)}%)"
            )
        if failure_delta > thresholds.max_failure_ratio_increase:
            stage_regressions.append(
                f"failure ratio aumentato di {round(failure_delta, 4)}"
            )

        compared_stages.append(
            {
                "users": users,
                "baseline_p95_ms": base_p95,
                "current_p95_ms": curr_p95,
                "baseline_failure_ratio": base_failure,
                "current_failure_ratio": curr_failure,
                "status": "fail" if stage_regressions else "pass",
                "regressions": stage_regressions,
            }
        )
        for item in stage_regressions:
            regressions.append(f"{name} stage {users}: {item}")

    return {
        "status": "fail" if regressions else "pass",
        "regressions": regressions,
        "compared_stages": compared_stages,
    }


def _compare_realtime_loadtest(
    baseline_report: dict[str, Any],
    current_report: dict[str, Any],
    *,
    thresholds: ComparisonThresholds,
) -> dict[str, Any]:
    baseline_stages = _stage_index(baseline_report)
    current_stages = _stage_index(current_report)
    overlapping = sorted(set(baseline_stages) & set(current_stages))
    if not overlapping:
        return {"status": "no_data", "regressions": [], "compared_stages": []}

    regressions: list[str] = []
    compared_stages: list[dict[str, Any]] = []
    for users in overlapping:
        base = baseline_stages[users]
        curr = current_stages[users]
        base_lag = float(base.get("lag_p95_ms") or 0.0)
        curr_lag = float(curr.get("lag_p95_ms") or 0.0)
        base_delivery = float(base.get("delivery_ratio") or 0.0)
        curr_delivery = float(curr.get("delivery_ratio") or 0.0)
        lag_ratio = ((curr_lag - base_lag) / base_lag) if base_lag > 0 else 0.0
        delivery_drop = base_delivery - curr_delivery
        stage_regressions: list[str] = []

        if bool(base.get("pass")) and not bool(curr.get("pass")):
            stage_regressions.append("stage passata a fail")
        if lag_ratio > thresholds.max_p95_regression_ratio:
            stage_regressions.append(
                f"lag p95 peggiorato oltre soglia ({round(lag_ratio * 100, 2)}%)"
            )
        if delivery_drop > thresholds.max_delivery_ratio_drop:
            stage_regressions.append(
                f"delivery ratio calato di {round(delivery_drop, 4)}"
            )

        compared_stages.append(
            {
                "users": users,
                "baseline_lag_p95_ms": base_lag,
                "current_lag_p95_ms": curr_lag,
                "baseline_delivery_ratio": base_delivery,
                "current_delivery_ratio": curr_delivery,
                "status": "fail" if stage_regressions else "pass",
                "regressions": stage_regressions,
            }
        )
        for item in stage_regressions:
            regressions.append(f"realtime stage {users}: {item}")

    return {
        "status": "fail" if regressions else "pass",
        "regressions": regressions,
        "compared_stages": compared_stages,
    }


def _compare_search_benchmark(
    baseline_report: dict[str, Any],
    current_report: dict[str, Any],
    *,
    thresholds: ComparisonThresholds,
) -> dict[str, Any]:
    baseline_overall = baseline_report.get("overall") if isinstance(baseline_report, dict) else {}
    current_overall = current_report.get("overall") if isinstance(current_report, dict) else {}
    if not isinstance(baseline_overall, dict) or not isinstance(current_overall, dict) or not baseline_overall or not current_overall:
        return {"status": "no_data", "regressions": [], "summary": {}}

    regressions: list[str] = []
    base_p95 = float(baseline_overall.get("p95_ms") or 0.0)
    curr_p95 = float(current_overall.get("p95_ms") or 0.0)
    p95_ratio = ((curr_p95 - base_p95) / base_p95) if base_p95 > 0 else 0.0
    if p95_ratio > thresholds.max_p95_regression_ratio:
        regressions.append(
            f"search benchmark p95 peggiorato oltre soglia ({round(p95_ratio * 100, 2)}%)"
        )

    base_failure = float(baseline_overall.get("failure_ratio") or 0.0)
    curr_failure = float(current_overall.get("failure_ratio") or 0.0)
    failure_delta = curr_failure - base_failure
    if failure_delta > thresholds.max_failure_ratio_increase:
        regressions.append(
            f"search benchmark failure ratio aumentato di {round(failure_delta, 4)}"
        )

    base_empty = float(baseline_overall.get("empty_ratio") or 0.0)
    curr_empty = float(current_overall.get("empty_ratio") or 0.0)
    empty_delta = curr_empty - base_empty
    if empty_delta > thresholds.max_empty_ratio_increase:
        regressions.append(
            f"search benchmark empty ratio aumentato di {round(empty_delta, 4)}"
        )

    if bool(baseline_report.get("status") == "pass") and bool(current_report.get("status") == "fail"):
        regressions.append("search benchmark passato da pass a fail")

    return {
        "status": "fail" if regressions else "pass",
        "regressions": regressions,
        "summary": {
            "baseline_p95_ms": base_p95,
            "current_p95_ms": curr_p95,
            "baseline_failure_ratio": base_failure,
            "current_failure_ratio": curr_failure,
            "baseline_empty_ratio": base_empty,
            "current_empty_ratio": curr_empty,
        },
    }


def compare_performance_baselines(
    baseline_bundle: dict[str, Any],
    current_bundle: dict[str, Any],
    *,
    thresholds: ComparisonThresholds | None = None,
) -> dict[str, Any]:
    current_thresholds = thresholds or ComparisonThresholds()
    loadtests_baseline = baseline_bundle.get("loadtests") if isinstance(baseline_bundle, dict) else {}
    loadtests_current = current_bundle.get("loadtests") if isinstance(current_bundle, dict) else {}

    runtime_budget = _compare_budget(
        baseline_bundle.get("runtime_budget", {}),
        current_bundle.get("runtime_budget", {}),
    )
    read_heavy = _compare_http_loadtest(
        "read_heavy",
        loadtests_baseline.get("read_heavy", {}) if isinstance(loadtests_baseline, dict) else {},
        loadtests_current.get("read_heavy", {}) if isinstance(loadtests_current, dict) else {},
        thresholds=current_thresholds,
    )
    auth_burst = _compare_http_loadtest(
        "auth_burst",
        loadtests_baseline.get("auth_burst", {}) if isinstance(loadtests_baseline, dict) else {},
        loadtests_current.get("auth_burst", {}) if isinstance(loadtests_current, dict) else {},
        thresholds=current_thresholds,
    )
    mixed_crud = _compare_http_loadtest(
        "mixed_crud",
        loadtests_baseline.get("mixed_crud", {}) if isinstance(loadtests_baseline, dict) else {},
        loadtests_current.get("mixed_crud", {}) if isinstance(loadtests_current, dict) else {},
        thresholds=current_thresholds,
    )
    realtime = _compare_realtime_loadtest(
        loadtests_baseline.get("realtime", {}) if isinstance(loadtests_baseline, dict) else {},
        loadtests_current.get("realtime", {}) if isinstance(loadtests_current, dict) else {},
        thresholds=current_thresholds,
    )
    search_benchmark = _compare_search_benchmark(
        baseline_bundle.get("search_benchmark", {}) if isinstance(baseline_bundle, dict) else {},
        current_bundle.get("search_benchmark", {}) if isinstance(current_bundle, dict) else {},
        thresholds=current_thresholds,
    )

    comparisons = {
        "runtime_budget": runtime_budget,
        "read_heavy": read_heavy,
        "auth_burst": auth_burst,
        "mixed_crud": mixed_crud,
        "realtime": realtime,
        "search_benchmark": search_benchmark,
    }
    regressions = [
        regression
        for comparison in comparisons.values()
        for regression in comparison.get("regressions", [])
    ]
    available_sections = sum(
        1 for comparison in comparisons.values() if comparison.get("status") != "no_data"
    )
    return {
        "status": "fail" if regressions else "pass",
        "baseline_label": baseline_bundle.get("label", "baseline"),
        "current_label": current_bundle.get("label", "current"),
        "available_sections": available_sections,
        "comparisons": comparisons,
        "regressions": regressions,
    }


def render_baseline_comparison_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Performance Baseline Comparison",
        "",
        f"- Baseline: `{report.get('baseline_label', 'baseline')}`",
        f"- Current: `{report.get('current_label', 'current')}`",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Sections compared: `{report.get('available_sections', 0)}`",
        "",
    ]

    for key, comparison in report.get("comparisons", {}).items():
        lines.extend(
            [
                f"## {key}",
                "",
                f"- Status: `{comparison.get('status', 'unknown')}`",
            ]
        )
        if key == "runtime_budget" and comparison.get("status") != "no_data":
            lines.append(
                f"- Score: `{comparison.get('baseline_score', 0)}% -> {comparison.get('current_score', 0)}%`"
            )
        if comparison.get("regressions"):
            lines.append("")
            for item in comparison["regressions"]:
                lines.append(f"- {item}")
        lines.append("")

    if report.get("regressions"):
        lines.extend(["## Regressions", ""])
        for item in report["regressions"]:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)
