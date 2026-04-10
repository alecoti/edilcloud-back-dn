from edilcloud.platform.performance_checkpoint import (
    build_performance_checkpoint_report,
    render_performance_checkpoint_markdown,
)


def test_build_performance_checkpoint_report_flags_failures_and_hot_paths():
    report = build_performance_checkpoint_report(
        label="checkpoint-a",
        generated_at="2026-04-05T12:30:00Z",
        runtime_budget={
            "budget": {
                "status": "fail",
                "score_percent": 40,
                "passing_rules": 2,
                "failing_rules": 1,
                "no_data_rules": 0,
                "failing": [
                    {
                        "key": "projects.overview",
                        "p95_ms": 1800.0,
                        "max_p95_ms": 900.0,
                        "error_ratio": 0.0,
                    }
                ],
                "missing_data": [],
            }
        },
        runtime_summary={
            "summary": {
                "http": {
                    "top_slowest": [
                        {
                            "method": "GET",
                            "path": "/api/v1/projects/12/overview",
                            "requests": 42,
                            "p95_ms": 1800.0,
                            "performance_status": "warning",
                        }
                    ]
                }
            }
        },
        route_exercise={
            "status": "warning",
            "requests": 9,
            "failures": 0,
            "routes": [
                {
                    "name": "project.overview",
                    "requests": 3,
                    "p95_ms": 1500.0,
                    "failure_ratio": 0.0,
                    "status": "warning",
                }
            ],
        },
        search_benchmark={
            "status": "pass",
            "overall": {
                "requests": 30,
                "p95_ms": 115.28,
                "failure_ratio": 0.0,
                "empty_ratio": 0.0,
            },
            "failures": [],
        },
        comparison_report={"status": "pass", "available_sections": 2, "regressions": []},
        artifacts={"baseline_bundle": "bundle.json"},
    )

    assert report["status"] == "fail"
    assert report["sections"]["runtime_budget"]["status"] == "fail"
    assert report["sections"]["runtime_summary"]["status"] == "warning"
    assert report["sections"]["route_exercise"]["status"] == "warning"
    assert any("projects.overview" in item for item in report["focus"])
    assert any("/api/v1/projects/12/overview" in item for item in report["focus"])
    assert any("project.overview" in item for item in report["focus"])


def test_render_performance_checkpoint_markdown_lists_focus_and_artifacts():
    report = build_performance_checkpoint_report(
        label="checkpoint-b",
        generated_at="2026-04-05T12:31:00Z",
        runtime_budget={
            "budget": {
                "status": "partial",
                "score_percent": 60,
                "passing_rules": 3,
                "failing_rules": 0,
                "no_data_rules": 1,
                "failing": [],
                "missing_data": [{"key": "search.global"}],
            }
        },
        runtime_summary={"summary": {"http": {"top_slowest": []}}},
        route_exercise={
            "status": "pass",
            "requests": 12,
            "failures": 0,
            "routes": [
                {
                    "name": "project.tasks",
                    "requests": 3,
                    "p95_ms": 210.0,
                    "failure_ratio": 0.0,
                    "status": "pass",
                }
            ],
        },
        search_benchmark={
            "status": "pass",
            "overall": {
                "requests": 30,
                "p95_ms": 115.28,
                "failure_ratio": 0.0,
                "empty_ratio": 0.0,
            },
            "failures": [],
        },
        comparison_report={"status": "no_data", "available_sections": 0, "regressions": []},
        artifacts={"history_dashboard": "docs/PERFORMANCE_HISTORY.md"},
    )

    markdown = render_performance_checkpoint_markdown(report)

    assert "# Performance Checkpoint" in markdown
    assert "checkpoint-b" in markdown
    assert "Route Exercise" in markdown
    assert "project.tasks" in markdown
    assert "Search Benchmark" in markdown
    assert "search.global" in markdown
    assert "docs/PERFORMANCE_HISTORY.md" in markdown
