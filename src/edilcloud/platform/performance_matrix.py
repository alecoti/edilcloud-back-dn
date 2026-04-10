from __future__ import annotations

from typing import Any


def _best_passing_stage(report: dict[str, Any] | None) -> int | None:
    if not isinstance(report, dict):
        return None
    stages = report.get("stages")
    if not isinstance(stages, list):
        return None
    passing: list[int] = []
    for stage in stages:
        if not isinstance(stage, dict) or not stage.get("pass"):
            continue
        try:
            passing.append(int(stage["users"]))
        except Exception:
            continue
    return max(passing) if passing else None


def _breaking_stage(report: dict[str, Any] | None) -> int | None:
    if not isinstance(report, dict):
        return None
    breaking = report.get("breaking_stage")
    try:
        return int(breaking) if breaking not in (None, "") else None
    except Exception:
        return None


def _scenario_status(report: dict[str, Any] | None) -> str:
    if not isinstance(report, dict):
        return "no_data"
    stages = report.get("stages")
    if not isinstance(stages, list) or not stages:
        return "no_data"
    return "fail" if _breaking_stage(report) is not None else "pass"


def _scenario_last_stage(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}
    stages = report.get("stages")
    if not isinstance(stages, list) or not stages:
        return {}
    return stages[-1] if isinstance(stages[-1], dict) else {}


def _http_metric_text(stage: dict[str, Any]) -> str:
    if not isinstance(stage, dict) or not stage:
        return "-"
    return "p95 {p95} ms / fail {fail}".format(
        p95=stage.get("p95_ms", 0),
        fail=stage.get("failure_ratio", 0),
    )


def _realtime_metric_text(stage: dict[str, Any]) -> str:
    if not isinstance(stage, dict) or not stage:
        return "-"
    return "lag p95 {p95} ms / delivery {delivery}".format(
        p95=stage.get("lag_p95_ms", 0),
        delivery=stage.get("delivery_ratio", 0),
    )


def build_scalability_matrix_report(
    *,
    label: str,
    generated_at: str,
    runtime_budget: dict[str, Any] | None = None,
    read_heavy: dict[str, Any] | None = None,
    auth_burst: dict[str, Any] | None = None,
    mixed_crud: dict[str, Any] | None = None,
    realtime: dict[str, Any] | None = None,
    search_benchmark: dict[str, Any] | None = None,
    comparison_report: dict[str, Any] | None = None,
    artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    scenarios = {
        "read_heavy": read_heavy if isinstance(read_heavy, dict) else {},
        "auth_burst": auth_burst if isinstance(auth_burst, dict) else {},
        "mixed_crud": mixed_crud if isinstance(mixed_crud, dict) else {},
        "realtime": realtime if isinstance(realtime, dict) else {},
    }
    runtime_budget_payload = runtime_budget if isinstance(runtime_budget, dict) else {}
    runtime_budget_data = runtime_budget_payload.get("budget")
    if not isinstance(runtime_budget_data, dict):
        runtime_budget_data = runtime_budget_payload
    search = search_benchmark if isinstance(search_benchmark, dict) else {}
    comparison = comparison_report if isinstance(comparison_report, dict) else {}

    scenario_sections: dict[str, Any] = {}
    focus: list[str] = []
    best_stage_candidates: list[tuple[str, int]] = []
    zero_pass_candidates: list[tuple[str, int]] = []

    for name, report in scenarios.items():
        status = _scenario_status(report)
        best_stage = _best_passing_stage(report)
        breaking_stage = _breaking_stage(report)
        last_stage = _scenario_last_stage(report)
        if best_stage is not None:
            best_stage_candidates.append((name, best_stage))
        elif breaking_stage is not None:
            zero_pass_candidates.append((name, breaking_stage))
        if status == "fail":
            if best_stage is None:
                focus.append(
                    "Scenario `{name}` non ha ancora nessuno stage passato e rompe gia a `{stage}`.".format(
                        name=name,
                        stage=breaking_stage,
                    )
                )
            else:
                focus.append(
                    "Scenario `{name}` rompe a stage `{stage}`".format(
                        name=name,
                        stage=breaking_stage,
                    )
                )
        elif status == "no_data":
            focus.append(f"Scenario `{name}` senza dati.")

        metric_text = (
            _realtime_metric_text(last_stage)
            if name == "realtime"
            else _http_metric_text(last_stage)
        )
        scenario_sections[name] = {
            "status": status,
            "best_passing_stage": best_stage,
            "breaking_stage": breaking_stage,
            "stages_run": len(report.get("stages", [])) if isinstance(report.get("stages"), list) else 0,
            "last_stage_metric": metric_text,
        }

    if zero_pass_candidates:
        bottleneck_name, bottleneck_stage = min(zero_pass_candidates, key=lambda item: item[1])
        focus.append(
            "Bottleneck corrente della matrice: `{name}` senza stage passati, primo break a `{stage}`.".format(
                name=bottleneck_name,
                stage=bottleneck_stage,
            )
        )
    elif best_stage_candidates:
        bottleneck_name, bottleneck_stage = min(best_stage_candidates, key=lambda item: item[1])
        focus.append(
            "Bottleneck corrente della matrice: `{name}` con best passing stage `{stage}`.".format(
                name=bottleneck_name,
                stage=bottleneck_stage,
            )
        )

    search_status = str(search.get("status") or "no_data")
    if search_status == "fail":
        focus.append("Search benchmark fuori soglia nella matrice.")
    elif search_status == "no_data":
        focus.append("Search benchmark non incluso nella matrice corrente.")

    runtime_budget_status = str(runtime_budget_data.get("status") or "no_data")
    if runtime_budget_status == "fail":
        focus.append(
            "Budget runtime del bundle matrice fuori soglia con score {score}%.".format(
                score=int(runtime_budget_data.get("score_percent") or 0)
            )
        )
    elif runtime_budget_status == "partial":
        focus.append(
            "Budget runtime del bundle matrice solo parziale con score {score}%.".format(
                score=int(runtime_budget_data.get("score_percent") or 0)
            )
        )

    comparison_status = str(comparison.get("status") or "no_data")
    comparison_regressions = [
        str(item)
        for item in comparison.get("regressions", [])
        if isinstance(item, str) and item
    ]
    if comparison_regressions:
        focus.append(f"Regressioni baseline aperte: {len(comparison_regressions)}")

    statuses = {section["status"] for section in scenario_sections.values()}
    if (
        "fail" in statuses
        or runtime_budget_status == "fail"
        or search_status == "fail"
        or comparison_status == "fail"
    ):
        overall_status = "fail"
    elif (
        "no_data" in statuses
        or runtime_budget_status in {"partial", "no_data"}
        or search_status == "no_data"
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
                "status": runtime_budget_status,
                "score_percent": int(runtime_budget_data.get("score_percent") or 0),
                "passing_rules": int(runtime_budget_data.get("passing_rules") or 0),
                "failing_rules": int(runtime_budget_data.get("failing_rules") or 0),
                "no_data_rules": int(runtime_budget_data.get("no_data_rules") or 0),
            },
            "scenarios": scenario_sections,
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


def render_scalability_matrix_markdown(report: dict[str, Any]) -> str:
    sections = report.get("sections", {}) if isinstance(report, dict) else {}
    scenarios = sections.get("scenarios", {}) if isinstance(sections, dict) else {}
    runtime_budget = sections.get("runtime_budget", {}) if isinstance(sections, dict) else {}
    search = sections.get("search_benchmark", {}) if isinstance(sections, dict) else {}
    baseline = sections.get("baseline_compare", {}) if isinstance(sections, dict) else {}

    lines = [
        "# Scalability Matrix",
        "",
        f"- Label: `{report.get('label', 'matrix')}`",
        f"- Generated at: `{report.get('generated_at', '-')}`",
        f"- Status: `{report.get('status', 'unknown')}`",
        "",
        "## Runtime Budget",
        "",
        f"- Status: `{runtime_budget.get('status', 'no_data')}`",
        f"- Score: `{runtime_budget.get('score_percent', 0)}%`",
        f"- Passing rules: `{runtime_budget.get('passing_rules', 0)}`",
        f"- Failing rules: `{runtime_budget.get('failing_rules', 0)}`",
        f"- No data rules: `{runtime_budget.get('no_data_rules', 0)}`",
        "",
        "## Scenarios",
        "",
        "| Scenario | Status | Best passing stage | Breaking stage | Last stage metric |",
        "| --- | --- | ---: | ---: | --- |",
    ]

    for name in ("read_heavy", "auth_burst", "mixed_crud", "realtime"):
        section = scenarios.get(name, {}) if isinstance(scenarios, dict) else {}
        lines.append(
            "| {name} | `{status}` | {best} | {breaking} | {metric} |".format(
                name=name,
                status=section.get("status", "no_data"),
                best=section.get("best_passing_stage") or "-",
                breaking=section.get("breaking_stage") or "-",
                metric=section.get("last_stage_metric") or "-",
            )
        )

    lines.extend(
        [
            "",
            "## Search",
            "",
            f"- Status: `{search.get('status', 'no_data')}`",
            f"- Requests: `{search.get('requests', 0)}`",
            f"- p95 ms: `{search.get('p95_ms', 0)}`",
            f"- Failure ratio: `{search.get('failure_ratio', 0)}`",
            f"- Empty ratio: `{search.get('empty_ratio', 0)}`",
            "",
            "## Baseline Compare",
            "",
            f"- Status: `{baseline.get('status', 'no_data')}`",
            f"- Available sections: `{baseline.get('available_sections', 0)}`",
        ]
    )

    regressions = baseline.get("regressions", [])
    if regressions:
        lines.append("- Regressions:")
        for item in regressions:
            lines.append(f"  - {item}")
    else:
        lines.append("- Nessuna regressione baseline aperta.")

    focus = report.get("focus", [])
    lines.extend(["", "## Focus"])
    if focus:
        for item in focus:
            lines.append(f"- {item}")
    else:
        lines.append("- Nessun focus aperto.")

    return "\n".join(lines)
