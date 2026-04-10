from edilcloud.platform.performance_matrix import (
    build_scalability_matrix_report,
    render_scalability_matrix_markdown,
)


def test_build_scalability_matrix_report_identifies_bottleneck_and_failures():
    report = build_scalability_matrix_report(
        label="matrix-local",
        generated_at="2026-04-05T12:00:00Z",
        runtime_budget={"budget": {"status": "partial", "score_percent": 80, "passing_rules": 4, "failing_rules": 1}},
        read_heavy={"stages": [{"users": 25, "p95_ms": 700.0, "failure_ratio": 0.0, "pass": True}]},
        auth_burst={
            "stages": [
                {"users": 10, "p95_ms": 620.0, "failure_ratio": 0.0, "pass": True},
                {"users": 25, "p95_ms": 980.0, "failure_ratio": 0.03, "pass": False},
            ],
            "breaking_stage": 25,
        },
        mixed_crud={"stages": [{"users": 10, "p95_ms": 1800.0, "failure_ratio": 0.0, "pass": True}]},
        realtime={"stages": [{"users": 25, "lag_p95_ms": 800.0, "delivery_ratio": 1.0, "pass": True}]},
        search_benchmark={"status": "pass", "overall": {"requests": 20, "p95_ms": 300.0, "failure_ratio": 0.0}},
    )

    assert report["status"] == "fail"
    assert report["sections"]["runtime_budget"]["status"] == "partial"
    assert report["sections"]["scenarios"]["auth_burst"]["status"] == "fail"
    assert report["sections"]["scenarios"]["read_heavy"]["best_passing_stage"] == 25
    assert any("Bottleneck" in item for item in report["focus"])
    assert any("auth_burst" in item for item in report["focus"])


def test_render_scalability_matrix_markdown_lists_all_scenarios():
    report = build_scalability_matrix_report(
        label="matrix-local",
        generated_at="2026-04-05T12:00:00Z",
        runtime_budget={"budget": {"status": "pass", "score_percent": 100, "passing_rules": 5, "failing_rules": 0}},
        read_heavy={"stages": [{"users": 25, "p95_ms": 700.0, "failure_ratio": 0.0, "pass": True}]},
        auth_burst={"stages": [{"users": 25, "p95_ms": 720.0, "failure_ratio": 0.0, "pass": True}]},
        mixed_crud={"stages": [{"users": 10, "p95_ms": 1800.0, "failure_ratio": 0.0, "pass": True}]},
        realtime={"stages": [{"users": 25, "lag_p95_ms": 800.0, "delivery_ratio": 1.0, "pass": True}]},
        search_benchmark={"status": "pass", "overall": {"requests": 20, "p95_ms": 300.0, "failure_ratio": 0.0}},
    )

    markdown = render_scalability_matrix_markdown(report)

    assert "# Scalability Matrix" in markdown
    assert "## Runtime Budget" in markdown
    assert "read_heavy" in markdown
    assert "auth_burst" in markdown
    assert "mixed_crud" in markdown
    assert "realtime" in markdown
