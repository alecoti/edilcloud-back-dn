from __future__ import annotations

from dataclasses import dataclass
import statistics
from typing import Any


@dataclass(frozen=True)
class SearchBenchmarkThresholds:
    max_failure_ratio: float = 0.01
    max_p95_ms: float = 1200.0
    max_empty_ratio: float = 1.0


def percentile(values: list[float], target_percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = max(0, min(len(ordered) - 1, round((target_percentile / 100) * (len(ordered) - 1))))
    return round(ordered[rank], 2)


def _group_summary(name: str, samples: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(item.get("latency_ms") or 0.0) for item in samples]
    total_requests = len(samples)
    failures = sum(1 for item in samples if not item.get("ok"))
    empty = sum(1 for item in samples if item.get("ok") and int(item.get("total") or 0) == 0)
    max_total = max((int(item.get("total") or 0) for item in samples), default=0)
    avg_total = (
        round(statistics.fmean(int(item.get("total") or 0) for item in samples), 2)
        if samples
        else 0.0
    )
    sections_hit = sorted(
        {
            section
            for item in samples
            for section in item.get("non_empty_sections", [])
            if isinstance(section, str) and section
        }
    )
    return {
        "name": name,
        "requests": total_requests,
        "failure_ratio": round(failures / total_requests, 4) if total_requests else 0.0,
        "empty_ratio": round(empty / total_requests, 4) if total_requests else 0.0,
        "avg_ms": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "p99_ms": percentile(latencies, 99),
        "max_ms": round(max(latencies), 2) if latencies else 0.0,
        "avg_total": avg_total,
        "max_total": max_total,
        "sections_hit": sections_hit,
    }


def build_search_benchmark_report(
    samples: list[dict[str, Any]],
    *,
    thresholds: SearchBenchmarkThresholds | None = None,
) -> dict[str, Any]:
    current_thresholds = thresholds or SearchBenchmarkThresholds()
    overall = _group_summary("overall", samples)
    by_query_index: dict[str, list[dict[str, Any]]] = {}
    by_category_index: dict[str, list[dict[str, Any]]] = {}
    by_pair_index: dict[str, list[dict[str, Any]]] = {}

    for sample in samples:
        query = str(sample.get("query") or "")
        category = str(sample.get("category") or "")
        by_query_index.setdefault(query, []).append(sample)
        by_category_index.setdefault(category, []).append(sample)
        by_pair_index.setdefault(f"{query}::{category}", []).append(sample)

    by_query = [_group_summary(name, group) for name, group in sorted(by_query_index.items())]
    by_category = [_group_summary(name, group) for name, group in sorted(by_category_index.items())]
    by_pair = [_group_summary(name, group) for name, group in sorted(by_pair_index.items())]

    failures = []
    if overall["failure_ratio"] > current_thresholds.max_failure_ratio:
        failures.append(
            f"failure ratio {overall['failure_ratio']} oltre budget {current_thresholds.max_failure_ratio}"
        )
    if overall["p95_ms"] > current_thresholds.max_p95_ms:
        failures.append(f"p95 {overall['p95_ms']} ms oltre budget {current_thresholds.max_p95_ms} ms")
    if overall["empty_ratio"] > current_thresholds.max_empty_ratio:
        failures.append(
            f"empty ratio {overall['empty_ratio']} oltre budget {current_thresholds.max_empty_ratio}"
        )

    return {
        "status": "fail" if failures else "pass",
        "thresholds": {
            "max_failure_ratio": current_thresholds.max_failure_ratio,
            "max_p95_ms": current_thresholds.max_p95_ms,
            "max_empty_ratio": current_thresholds.max_empty_ratio,
        },
        "overall": overall,
        "by_query": by_query,
        "by_category": by_category,
        "by_query_category": by_pair,
        "failures": failures,
        "query_count": len(by_query),
        "category_count": len(by_category),
    }


def render_search_benchmark_markdown(report: dict[str, Any]) -> str:
    overall = report.get("overall", {})
    lines = [
        "# Search Benchmark",
        "",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Requests: `{overall.get('requests', 0)}`",
        f"- Failure ratio: `{overall.get('failure_ratio', 0)}`",
        f"- Empty ratio: `{overall.get('empty_ratio', 0)}`",
        f"- p95: `{overall.get('p95_ms', 0)} ms`",
        f"- Queries: `{report.get('query_count', 0)}`",
        f"- Categories: `{report.get('category_count', 0)}`",
        "",
        "## By Query",
        "",
        "| Query | Requests | Empty ratio | p95 ms | Max total | Sections hit |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report.get("by_query", []):
        lines.append(
            "| {name} | {requests} | {empty_ratio} | {p95_ms} | {max_total} | {sections} |".format(
                name=item.get("name", "-"),
                requests=item.get("requests", 0),
                empty_ratio=item.get("empty_ratio", 0),
                p95_ms=item.get("p95_ms", 0),
                max_total=item.get("max_total", 0),
                sections=", ".join(item.get("sections_hit", [])) or "-",
            )
        )

    failures = report.get("failures", [])
    if failures:
        lines.extend(["", "## Budget Breaches", ""])
        for item in failures:
            lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)
