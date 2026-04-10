from edilcloud.platform.performance_baseline import (
    build_performance_baseline_bundle,
    compare_performance_baselines,
)


def test_compare_performance_baselines_detects_http_regression():
    baseline = build_performance_baseline_bundle(
        label="baseline",
        generated_at="2026-04-05T00:00:00Z",
        read_heavy={
            "stages": [
                {
                    "users": 25,
                    "p95_ms": 800.0,
                    "failure_ratio": 0.0,
                    "pass": True,
                }
            ]
        },
    )
    current = build_performance_baseline_bundle(
        label="current",
        generated_at="2026-04-05T01:00:00Z",
        read_heavy={
            "stages": [
                {
                    "users": 25,
                    "p95_ms": 1100.0,
                    "failure_ratio": 0.0,
                    "pass": False,
                }
            ]
        },
    )

    report = compare_performance_baselines(baseline, current)

    assert report["status"] == "fail"
    assert any("read_heavy" in item for item in report["regressions"])


def test_compare_performance_baselines_detects_auth_burst_regression():
    baseline = build_performance_baseline_bundle(
        label="baseline",
        generated_at="2026-04-05T00:00:00Z",
        auth_burst={
            "stages": [
                {
                    "users": 25,
                    "p95_ms": 500.0,
                    "failure_ratio": 0.0,
                    "pass": True,
                }
            ]
        },
    )
    current = build_performance_baseline_bundle(
        label="current",
        generated_at="2026-04-05T01:00:00Z",
        auth_burst={
            "stages": [
                {
                    "users": 25,
                    "p95_ms": 760.0,
                    "failure_ratio": 0.0,
                    "pass": False,
                }
            ]
        },
    )

    report = compare_performance_baselines(baseline, current)

    assert report["status"] == "fail"
    assert any("auth_burst" in item for item in report["regressions"])


def test_compare_performance_baselines_detects_runtime_budget_score_drop():
    baseline = build_performance_baseline_bundle(
        label="baseline",
        generated_at="2026-04-05T00:00:00Z",
        runtime_budget={
            "budget": {
                "score_percent": 80,
                "rules": [{"key": "health", "status": "pass"}],
            }
        },
    )
    current = build_performance_baseline_bundle(
        label="current",
        generated_at="2026-04-05T01:00:00Z",
        runtime_budget={
            "budget": {
                "score_percent": 40,
                "rules": [{"key": "health", "status": "fail"}],
            }
        },
    )

    report = compare_performance_baselines(baseline, current)

    assert report["status"] == "fail"
    assert any("runtime budget score" in item for item in report["regressions"])


def test_compare_performance_baselines_detects_search_benchmark_regression():
    baseline = build_performance_baseline_bundle(
        label="baseline",
        generated_at="2026-04-05T00:00:00Z",
        search_benchmark={
            "status": "pass",
            "overall": {
                "p95_ms": 200.0,
                "failure_ratio": 0.0,
                "empty_ratio": 0.0,
            },
        },
    )
    current = build_performance_baseline_bundle(
        label="current",
        generated_at="2026-04-05T01:00:00Z",
        search_benchmark={
            "status": "fail",
            "overall": {
                "p95_ms": 320.0,
                "failure_ratio": 0.0,
                "empty_ratio": 0.0,
            },
        },
    )

    report = compare_performance_baselines(baseline, current)

    assert report["status"] == "fail"
    assert any("search benchmark" in item for item in report["regressions"])
