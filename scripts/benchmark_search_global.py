from __future__ import annotations

import asyncio
import argparse
import json
from pathlib import Path
import time
from typing import Any

import httpx

from edilcloud.platform.search_benchmark import (
    SearchBenchmarkThresholds,
    build_search_benchmark_report,
    render_search_benchmark_markdown,
)


DEFAULT_QUERIES = "smoke,project,torino,core,milano"
DEFAULT_CATEGORIES = "all,projects"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark the global search route through the real frontend API path.",
    )
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--email", default="project.detail.owner@example.com")
    parser.add_argument("--password", default="devpass123")
    parser.add_argument("--queries", default=DEFAULT_QUERIES)
    parser.add_argument("--categories", default=DEFAULT_CATEGORIES)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--max-failure-ratio", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1200.0)
    parser.add_argument("--max-empty-ratio", type=float, default=1.0)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", default="")
    parser.add_argument("--fail-on-threshold", action="store_true")
    return parser.parse_args()


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


async def login(client: httpx.AsyncClient, *, email: str, password: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"usernameOrEmail": email, "password": password},
    )
    if response.status_code != 200:
        raise RuntimeError(f"Login fallito: {response.status_code} {response.text[:180]}")


async def fetch_search_sample(
    client: httpx.AsyncClient,
    *,
    query: str,
    category: str,
    limit: int,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    response = await client.get(
        "/api/search/global",
        params={"q": query, "category": category, "limit": limit},
    )
    latency_ms = (time.perf_counter() - started_at) * 1000
    ok = response.status_code == 200
    payload = response.json() if ok else {}
    sections = payload.get("sections", {}) if isinstance(payload, dict) else {}
    non_empty_sections = [
        key for key, value in sections.items() if isinstance(value, list) and value
    ] if isinstance(sections, dict) else []
    total = int(payload.get("total") or 0) if isinstance(payload, dict) else 0
    return {
        "query": query,
        "category": category,
        "ok": ok,
        "status_code": response.status_code,
        "latency_ms": round(latency_ms, 2),
        "total": total,
        "non_empty_sections": non_empty_sections,
        "sample_error": "" if ok else response.text[:180],
    }


async def main_async() -> int:
    args = parse_args()
    queries = parse_csv(args.queries)
    categories = parse_csv(args.categories)
    if not queries:
        raise SystemExit("Specifica almeno una query con --queries.")
    if not categories:
        raise SystemExit("Specifica almeno una category con --categories.")

    timeout = httpx.Timeout(20.0, connect=10.0)
    samples: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout, follow_redirects=False) as client:
        await login(client, email=args.email, password=args.password)
        for _ in range(max(1, args.repeats)):
            for query in queries:
                for category in categories:
                    samples.append(
                        await fetch_search_sample(
                            client,
                            query=query,
                            category=category,
                            limit=max(1, min(args.limit, 12)),
                        )
                    )

    report = build_search_benchmark_report(
        samples,
        thresholds=SearchBenchmarkThresholds(
            max_failure_ratio=args.max_failure_ratio,
            max_p95_ms=args.max_p95_ms,
            max_empty_ratio=args.max_empty_ratio,
        ),
    )
    report["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    report["base_url"] = args.base_url
    report["queries"] = queries
    report["categories"] = categories
    report["repeats"] = args.repeats
    report["samples"] = samples

    rendered = json.dumps(report, indent=2) if args.format == "json" else render_search_benchmark_markdown(report)
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    print(rendered)
    if args.fail_on_threshold and report.get("status") == "fail":
        return 1
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
