from __future__ import annotations

from typing import Any


def _runtime_budget_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    budget = payload.get("budget")
    return budget if isinstance(budget, dict) else payload


def _runtime_summary_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    summary = payload.get("summary")
    return summary if isinstance(summary, dict) else payload


def _normalized_status(value: str | None, *, default: str = "no_data") -> str:
    status = (value or default).strip().lower()
    return status or default


def _hot_paths(summary_payload: dict[str, Any]) -> list[dict[str, Any]]:
    http_summary = summary_payload.get("http")
    if not isinstance(http_summary, dict):
        return []
    top_slowest = http_summary.get("top_slowest")
    if not isinstance(top_slowest, list):
        return []

    paths: list[dict[str, Any]] = []
    for item in top_slowest:
        if not isinstance(item, dict):
            continue
        performance_status = str(item.get("performance_status") or "ok")
        if performance_status == "ok":
            continue
        paths.append(
            {
                "method": item.get("method", "GET"),
                "path": item.get("path", "/"),
                "requests": int(item.get("requests") or 0),
                "p95_ms": float(item.get("p95_ms") or 0.0),
                "performance_status": performance_status,
            }
        )
    return paths


def build_performance_checkpoint_report(
    *,
    label: str,
    generated_at: str,
    runtime_budget: dict[str, Any] | None,
    runtime_summary: dict[str, Any] | None,
    route_exercise: dict[str, Any] | None = None,
    search_benchmark: dict[str, Any] | None = None,
    comparison_report: dict[str, Any] | None = None,
    artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    budget = _runtime_budget_payload(runtime_budget)
    summary = _runtime_summary_payload(runtime_summary)
    exercise = route_exercise if isinstance(route_exercise, dict) else {}
    search = search_benchmark if isinstance(search_benchmark, dict) else {}
    comparison = comparison_report if isinstance(comparison_report, dict) else {}

    runtime_status = _normalized_status(str(budget.get("status") or "no_data"))
    route_exercise_status = _normalized_status(str(exercise.get("status") or "no_data"))
    search_status = _normalized_status(str(search.get("status") or "no_data"))
    comparison_status = _normalized_status(str(comparison.get("status") or "no_data"))

    failing_rules = [
        {
            "key": item.get("key", "-"),
            "p95_ms": item.get("p95_ms", 0),
            "max_p95_ms": item.get("max_p95_ms", 0),
            "error_ratio": item.get("error_ratio", 0),
        }
        for item in budget.get("failing", [])
        if isinstance(item, dict)
    ]
    missing_rules = [
        str(item.get("key", "-"))
        for item in budget.get("missing_data", [])
        if isinstance(item, dict)
    ]
    hot_paths = _hot_paths(summary)
    route_samples = [
        item for item in exercise.get("routes", []) if isinstance(item, dict)
    ]
    search_failures = [
        str(item)
        for item in search.get("failures", [])
        if isinstance(item, str) and item
    ]
    comparison_regressions = [
        str(item)
        for item in comparison.get("regressions", [])
        if isinstance(item, str) and item
    ]

    focus: list[str] = []
    for item in failing_rules:
        focus.append(
            "Budget fuori soglia su `{key}`: p95 {p95_ms} ms su budget {max_p95_ms} ms".format(
                key=item["key"],
                p95_ms=item["p95_ms"],
                max_p95_ms=item["max_p95_ms"],
            )
        )
    for item in hot_paths[:3]:
        focus.append(
            "Hot path {status}: `{method} {path}` con p95 {p95_ms} ms su {requests} richieste".format(
                status=item["performance_status"],
                method=item["method"],
                path=item["path"],
                p95_ms=round(float(item["p95_ms"]), 2),
                requests=item["requests"],
            )
        )
    for item in route_samples:
        if str(item.get("status")) in {"fail", "warning"}:
            focus.append(
                "Route exercise fuori soglia su `{name}`: p95 {p95_ms} ms con failure ratio {failure_ratio}".format(
                    name=item.get("name", "-"),
                    p95_ms=item.get("p95_ms", 0),
                    failure_ratio=item.get("failure_ratio", 0),
                )
            )
    for item in search_failures:
        focus.append(f"Search benchmark: {item}")
    if comparison_regressions:
        focus.append(f"Regressioni baseline aperte: {len(comparison_regressions)}")
    if missing_rules and runtime_status != "pass":
        focus.append(
            "Rule ancora senza dati sufficienti: {keys}".format(
                keys=", ".join(missing_rules[:3])
            )
        )

    if (
        runtime_status == "fail"
        or route_exercise_status == "fail"
        or search_status == "fail"
        or comparison_status == "fail"
    ):
        overall_status = "fail"
    elif (
        runtime_status in {"partial", "no_data"}
        or route_exercise_status in {"warning", "no_data"}
        or search_status == "no_data"
        or comparison_status == "no_data"
        or bool(hot_paths)
    ):
        overall_status = "needs_attention"
    else:
        overall_status = "pass"

    return {
        "label": label,
        "generated_at": generated_at,
        "status": overall_status,
        "sections": {
            "runtime_budget": {
                "status": runtime_status,
                "score_percent": int(budget.get("score_percent") or 0),
                "passing_rules": int(budget.get("passing_rules") or 0),
                "failing_rules": int(budget.get("failing_rules") or 0),
                "no_data_rules": int(budget.get("no_data_rules") or 0),
                "failing": failing_rules,
                "missing": missing_rules,
            },
            "runtime_summary": {
                "status": "warning" if hot_paths else "ok",
                "hot_paths": hot_paths,
            },
            "route_exercise": {
                "status": route_exercise_status,
                "routes": route_samples,
                "requests": int(exercise.get("requests") or 0),
                "failures": int(exercise.get("failures") or 0),
            },
            "search_benchmark": {
                "status": search_status,
                "requests": int(search.get("overall", {}).get("requests") or 0)
                if isinstance(search.get("overall"), dict)
                else 0,
                "p95_ms": search.get("overall", {}).get("p95_ms", 0)
                if isinstance(search.get("overall"), dict)
                else 0,
                "failure_ratio": search.get("overall", {}).get("failure_ratio", 0)
                if isinstance(search.get("overall"), dict)
                else 0,
                "empty_ratio": search.get("overall", {}).get("empty_ratio", 0)
                if isinstance(search.get("overall"), dict)
                else 0,
                "failures": search_failures,
            },
            "baseline_compare": {
                "status": comparison_status,
                "available_sections": int(comparison.get("available_sections") or 0),
                "regressions": comparison_regressions,
            },
        },
        "focus": focus,
        "artifacts": artifacts or {},
    }


def render_performance_checkpoint_markdown(report: dict[str, Any]) -> str:
    sections = report.get("sections", {}) if isinstance(report, dict) else {}
    runtime_budget = sections.get("runtime_budget", {}) if isinstance(sections, dict) else {}
    runtime_summary = sections.get("runtime_summary", {}) if isinstance(sections, dict) else {}
    route_exercise = sections.get("route_exercise", {}) if isinstance(sections, dict) else {}
    search = sections.get("search_benchmark", {}) if isinstance(sections, dict) else {}
    baseline = sections.get("baseline_compare", {}) if isinstance(sections, dict) else {}

    lines = [
        "# Performance Checkpoint",
        "",
        f"- Label: `{report.get('label', 'checkpoint')}`",
        f"- Generated at: `{report.get('generated_at', '-')}`",
        f"- Status: `{report.get('status', 'unknown')}`",
        "",
        "## Runtime Budget",
        "",
        f"- Status: `{runtime_budget.get('status', 'unknown')}`",
        f"- Score: `{runtime_budget.get('score_percent', 0)}%`",
        f"- Passing rules: `{runtime_budget.get('passing_rules', 0)}`",
        f"- Failing rules: `{runtime_budget.get('failing_rules', 0)}`",
        f"- No data rules: `{runtime_budget.get('no_data_rules', 0)}`",
        "",
        "## Runtime Hot Paths",
        "",
    ]

    hot_paths = runtime_summary.get("hot_paths", [])
    if hot_paths:
        lines.extend(
            [
                "| Path | Status | Requests | p95 ms |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        for item in hot_paths:
            lines.append(
                "| {method} {path} | `{status}` | {requests} | {p95_ms} |".format(
                    method=item.get("method", "GET"),
                    path=item.get("path", "/"),
                    status=item.get("performance_status", "ok"),
                    requests=item.get("requests", 0),
                    p95_ms=item.get("p95_ms", 0),
                )
            )
    else:
        lines.append("- Nessun hot path sopra la soglia di warning nel summary corrente.")

    lines.extend(
        [
            "",
            "## Route Exercise",
            "",
            f"- Status: `{route_exercise.get('status', 'no_data')}`",
            f"- Requests: `{route_exercise.get('requests', 0)}`",
            f"- Failures: `{route_exercise.get('failures', 0)}`",
            "",
        ]
    )
    exercised_routes = route_exercise.get("routes", [])
    if exercised_routes:
        lines.extend(
            [
                "| Route | Status | Requests | p95 ms | Failure ratio |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for item in exercised_routes:
            lines.append(
                "| {name} | `{status}` | {requests} | {p95_ms} | {failure_ratio} |".format(
                    name=item.get("name", "-"),
                    status=item.get("status", "unknown"),
                    requests=item.get("requests", 0),
                    p95_ms=item.get("p95_ms", 0),
                    failure_ratio=item.get("failure_ratio", 0),
                )
            )
    else:
        lines.append("- Nessuna route esercitata nel checkpoint.")

    lines.extend(
        [
            "",
            "## Search Benchmark",
            "",
            f"- Status: `{search.get('status', 'no_data')}`",
            f"- Requests: `{search.get('requests', 0)}`",
            f"- p95: `{search.get('p95_ms', 0)} ms`",
            f"- Failure ratio: `{search.get('failure_ratio', 0)}`",
            f"- Empty ratio: `{search.get('empty_ratio', 0)}`",
            "",
            "## Baseline Compare",
            "",
            f"- Status: `{baseline.get('status', 'no_data')}`",
            f"- Sections compared: `{baseline.get('available_sections', 0)}`",
        ]
    )

    focus = report.get("focus", [])
    if focus:
        lines.extend(["", "## Focus", ""])
        for item in focus:
            lines.append(f"- {item}")

    artifacts = report.get("artifacts", {})
    if isinstance(artifacts, dict) and artifacts:
        lines.extend(["", "## Artifacts", ""])
        for key, value in artifacts.items():
            lines.append(f"- `{key}`: `{value}`")

    lines.append("")
    return "\n".join(lines)
