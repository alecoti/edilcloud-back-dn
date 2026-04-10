from edilcloud.platform.search_benchmark import (
    SearchBenchmarkThresholds,
    build_search_benchmark_report,
)


def test_build_search_benchmark_report_marks_fail_when_p95_exceeds_budget():
    samples = [
        {"query": "naviglio", "category": "all", "ok": True, "latency_ms": 900.0, "total": 3, "non_empty_sections": ["projects"]},
        {"query": "naviglio", "category": "all", "ok": True, "latency_ms": 1800.0, "total": 3, "non_empty_sections": ["projects"]},
    ]

    report = build_search_benchmark_report(
        samples,
        thresholds=SearchBenchmarkThresholds(max_p95_ms=1000.0),
    )

    assert report["status"] == "fail"
    assert any("p95" in item for item in report["failures"])


def test_build_search_benchmark_report_summarizes_queries_and_categories():
    samples = [
        {"query": "naviglio", "category": "all", "ok": True, "latency_ms": 100.0, "total": 4, "non_empty_sections": ["projects", "documents"]},
        {"query": "task", "category": "tasks", "ok": True, "latency_ms": 120.0, "total": 2, "non_empty_sections": ["tasks"]},
    ]

    report = build_search_benchmark_report(samples)

    assert report["query_count"] == 2
    assert report["category_count"] == 2
    naviglio = next(item for item in report["by_query"] if item["name"] == "naviglio")
    assert "projects" in naviglio["sections_hit"]
