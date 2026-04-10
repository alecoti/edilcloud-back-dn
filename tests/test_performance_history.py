from edilcloud.platform.performance_history import (
    add_history_entry,
    render_performance_history_markdown,
    summarize_performance_bundle,
)


def test_summarize_performance_bundle_extracts_scores_and_stages():
    bundle = {
        "label": "local-dev",
        "generated_at": "2026-04-05T12:00:00Z",
        "runtime_budget": {
            "budget": {
                "status": "partial",
                "score_percent": 60,
            }
        },
        "loadtests": {
            "read_heavy": {"stages": [{"users": 25, "pass": True}, {"users": 50, "pass": False}]},
            "auth_burst": {"stages": [{"users": 25, "pass": True}, {"users": 50, "pass": False}]},
            "mixed_crud": {"stages": [{"users": 10, "pass": True}]},
            "realtime": {"stages": [{"users": 25, "pass": True}, {"users": 100, "pass": True}]},
        },
        "search_benchmark": {
            "status": "pass",
            "overall": {"p95_ms": 302.75, "empty_ratio": 0.0},
        },
    }

    entry = summarize_performance_bundle(bundle, artifact_path="docs/performance-history/bundles/x.json")

    assert entry["kind"] == "generic"
    assert entry["runtime_budget_score"] == 60
    assert entry["read_heavy_best_stage"] == 25
    assert entry["auth_burst_best_stage"] == 25
    assert entry["mixed_crud_best_stage"] == 10
    assert entry["realtime_best_stage"] == 100
    assert entry["search_benchmark_status"] == "pass"
    assert entry["search_benchmark_p95_ms"] == 302.75
    assert entry["search_benchmark_empty_ratio"] == 0.0


def test_render_performance_history_markdown_lists_entries():
    manifest = add_history_entry(
        {"version": 1, "entries": []},
        {
            "kind": "checkpoint",
            "label": "local-dev",
            "generated_at": "2026-04-05T12:00:00Z",
            "artifact_path": "bundle.json",
            "runtime_budget_status": "pass",
            "runtime_budget_score": 80,
            "read_heavy_best_stage": 25,
            "auth_burst_best_stage": 25,
            "mixed_crud_best_stage": 10,
            "realtime_best_stage": 100,
            "search_benchmark_status": "pass",
            "search_benchmark_p95_ms": 302.75,
            "comparison_status": "pass",
            "comparison_regressions": 0,
            "comparison_path": "comparison.json",
        },
    )

    markdown = render_performance_history_markdown(manifest)

    assert "# Performance History" in markdown
    assert "Kind" in markdown
    assert "checkpoint" in markdown
    assert "local-dev" in markdown
    assert "pass (80%)" in markdown
    assert "Search p95" in markdown
    assert "Auth burst best stage" in markdown
    assert "pass / 302.75 ms" in markdown
