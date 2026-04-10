from __future__ import annotations

import asyncio
import argparse
import json
from pathlib import Path
import subprocess
import statistics
import sys
import time
from typing import Any

import httpx

from edilcloud.platform.performance_budget import evaluate_runtime_summary
from edilcloud.platform.performance_checkpoint import (
    build_performance_checkpoint_report,
    render_performance_checkpoint_markdown,
)


DEFAULT_SEARCH_QUERIES = "smoke,project,torino,core,milano"
DEFAULT_SEARCH_CATEGORIES = "all,projects"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a single performance checkpoint that stitches runtime budget, search benchmark, baseline bundle and history.",
    )
    parser.add_argument("--label", default="local-dev-checkpoint")
    parser.add_argument("--backend-base-url", default="http://localhost:8001")
    parser.add_argument("--frontend-base-url", default="http://localhost:3000")
    parser.add_argument("--email", default="project.detail.owner@example.com")
    parser.add_argument("--password", default="devpass123")
    parser.add_argument("--search-queries", default=DEFAULT_SEARCH_QUERIES)
    parser.add_argument("--search-categories", default=DEFAULT_SEARCH_CATEGORIES)
    parser.add_argument("--search-repeats", type=int, default=3)
    parser.add_argument("--search-limit", type=int, default=6)
    parser.add_argument("--search-max-failure-ratio", type=float, default=0.01)
    parser.add_argument("--search-max-p95-ms", type=float, default=1200.0)
    parser.add_argument("--search-max-empty-ratio", type=float, default=1.0)
    parser.add_argument("--project-id", type=int, default=0)
    parser.add_argument("--exercise-repeats", type=int, default=3)
    parser.add_argument("--route-max-failure-ratio", type=float, default=0.01)
    parser.add_argument("--route-max-p95-ms", type=float, default=1200.0)
    parser.add_argument("--history-dir", default="docs/performance-history")
    parser.add_argument("--dashboard", default="docs/PERFORMANCE_HISTORY.md")
    parser.add_argument("--work-dir", default=".tmp/performance-checkpoints")
    parser.add_argument("--skip-runtime-exercise", action="store_true")
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--compare-to-latest", action="store_true")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", default="")
    parser.add_argument("--fail-on-attention", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_python_script(script_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _fetch_json(base_url: str, path: str) -> dict[str, Any]:
    with httpx.Client(base_url=base_url, timeout=20.0) as client:
        response = client.get(path)
        response.raise_for_status()
        return response.json()


def _post_json(base_url: str, path: str) -> dict[str, Any]:
    with httpx.Client(base_url=base_url, timeout=20.0) as client:
        response = client.post(path)
        response.raise_for_status()
        return response.json()


def _percentile(values: list[float], target_percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = max(0, min(len(ordered) - 1, round((target_percentile / 100) * (len(ordered) - 1))))
    return round(ordered[rank], 2)


async def _login_frontend(
    client: httpx.AsyncClient,
    *,
    email: str,
    password: str,
) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"usernameOrEmail": email, "password": password},
    )
    response.raise_for_status()


async def _resolve_project_id(
    client: httpx.AsyncClient,
    *,
    preferred_project_id: int,
) -> int | None:
    if preferred_project_id > 0:
        return preferred_project_id
    response = await client.get("/api/projects")
    response.raise_for_status()
    payload = response.json()
    items = payload if isinstance(payload, list) else payload.get("items") or payload.get("value") or []
    if not isinstance(items, list) or not items:
        return None
    try:
        return int(items[0]["id"])
    except Exception:
        return None


def _summarize_route_exercise(
    samples: list[dict[str, Any]],
    *,
    max_failure_ratio: float,
    max_p95_ms: float,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in samples:
        name = str(item.get("name") or "unknown")
        grouped.setdefault(name, []).append(item)

    routes: list[dict[str, Any]] = []
    total_failures = 0
    for name, group in sorted(grouped.items()):
        latencies = [float(item.get("latency_ms") or 0.0) for item in group]
        failures = sum(1 for item in group if not item.get("ok"))
        requests = len(group)
        failure_ratio = round(failures / requests, 4) if requests else 0.0
        p95_ms = _percentile(latencies, 95)
        if failures > 0 or failure_ratio > max_failure_ratio:
            status = "fail"
        elif p95_ms > max_p95_ms:
            status = "warning"
        else:
            status = "pass"
        routes.append(
            {
                "name": name,
                "requests": requests,
                "failures": failures,
                "failure_ratio": failure_ratio,
                "avg_ms": round(statistics.fmean(latencies), 2) if latencies else 0.0,
                "p95_ms": p95_ms,
                "max_ms": round(max(latencies), 2) if latencies else 0.0,
                "status": status,
            }
        )
        total_failures += failures

    statuses = {item["status"] for item in routes}
    if "fail" in statuses:
        overall_status = "fail"
    elif "warning" in statuses:
        overall_status = "warning"
    elif routes:
        overall_status = "pass"
    else:
        overall_status = "no_data"

    return {
        "status": overall_status,
        "requests": len(samples),
        "failures": total_failures,
        "routes": routes,
    }


async def _exercise_runtime_paths(
    *,
    backend_base_url: str,
    frontend_base_url: str,
    email: str,
    password: str,
    project_id: int,
    repeats: int,
    max_failure_ratio: float,
    max_p95_ms: float,
) -> dict[str, Any]:
    timeout = httpx.Timeout(20.0, connect=10.0)
    samples: list[dict[str, Any]] = []
    async with httpx.AsyncClient(base_url=frontend_base_url, timeout=timeout) as frontend_client:
        await _login_frontend(frontend_client, email=email, password=password)
        resolved_project_id = await _resolve_project_id(
            frontend_client,
            preferred_project_id=project_id,
        )
        if resolved_project_id is None:
            raise RuntimeError("Impossibile risolvere un project id per il route exercise.")

        route_plan = [
            ("auth.session", "/api/auth/session"),
            ("projects.list", "/api/projects"),
            ("feed.list", "/api/feed"),
            ("notifications.list", "/api/notifications"),
            ("project.overview", f"/api/projects/{resolved_project_id}/overview"),
            ("project.tasks", f"/api/projects/{resolved_project_id}/tasks"),
            ("project.documents", f"/api/projects/{resolved_project_id}/documents"),
            ("project.gantt", f"/api/projects/{resolved_project_id}/gantt"),
            ("assistant.state", f"/api/projects/{resolved_project_id}/assistant"),
        ]
        for _ in range(max(1, repeats)):
            for name, path in route_plan:
                started_at = time.perf_counter()
                response = await frontend_client.get(path)
                samples.append(
                    {
                        "name": name,
                        "path": path,
                        "status_code": response.status_code,
                        "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                        "ok": response.status_code == 200,
                    }
                )

    async with httpx.AsyncClient(base_url=backend_base_url, timeout=timeout) as backend_client:
        for _ in range(max(1, repeats)):
            started_at = time.perf_counter()
            response = await backend_client.get("/api/v1/health")
            samples.append(
                {
                    "name": "backend.health",
                    "path": "/api/v1/health",
                    "status_code": response.status_code,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                    "ok": response.status_code == 200,
                }
            )

    return _summarize_route_exercise(
        samples,
        max_failure_ratio=max_failure_ratio,
        max_p95_ms=max_p95_ms,
    )


def main() -> int:
    args = parse_args()
    scripts_dir = Path(__file__).resolve().parent
    work_root = Path(args.work_dir).resolve()
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    checkpoint_dir = work_root / f"{timestamp}--{args.label}"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    _post_json(args.backend_base_url, "/api/v1/health/metrics/reset")

    route_exercise: dict[str, Any] = {}
    route_exercise_path = checkpoint_dir / "route-exercise.json"
    if not args.skip_runtime_exercise:
        route_exercise = asyncio.run(
            _exercise_runtime_paths(
                backend_base_url=args.backend_base_url,
                frontend_base_url=args.frontend_base_url,
                email=args.email,
                password=args.password,
                project_id=args.project_id,
                repeats=args.exercise_repeats,
                max_failure_ratio=args.route_max_failure_ratio,
                max_p95_ms=args.route_max_p95_ms,
            )
        )
        _write_json(route_exercise_path, route_exercise)

    search_report: dict[str, Any] = {}
    search_report_path = checkpoint_dir / "search-benchmark.json"
    if not args.skip_search:
        _run_python_script(
            scripts_dir / "benchmark_search_global.py",
            [
                "--base-url",
                args.frontend_base_url,
                "--email",
                args.email,
                "--password",
                args.password,
                "--queries",
                args.search_queries,
                "--categories",
                args.search_categories,
                "--repeats",
                str(args.search_repeats),
                "--limit",
                str(args.search_limit),
                "--max-failure-ratio",
                str(args.search_max_failure_ratio),
                "--max-p95-ms",
                str(args.search_max_p95_ms),
                "--max-empty-ratio",
                str(args.search_max_empty_ratio),
                "--format",
                "json",
                "--output",
                str(search_report_path),
            ],
        )
        search_report = _read_json(search_report_path)

    runtime_summary = _fetch_json(args.backend_base_url, "/api/v1/health/metrics/summary")
    runtime_budget = {
        "status": "ok",
        "budget": evaluate_runtime_summary(runtime_summary.get("summary", {})),
    }

    runtime_budget_path = checkpoint_dir / "runtime-budget.json"
    runtime_summary_path = checkpoint_dir / "runtime-summary.json"
    _write_json(runtime_budget_path, runtime_budget)
    _write_json(runtime_summary_path, runtime_summary)

    baseline_bundle_path = checkpoint_dir / "baseline-bundle.json"
    capture_args = [
        "--kind",
        "checkpoint",
        "--base-url",
        args.backend_base_url,
        "--label",
        args.label,
        "--output",
        str(baseline_bundle_path),
    ]
    if search_report_path.exists():
        capture_args.extend(["--search-benchmark-report", str(search_report_path)])
    _run_python_script(scripts_dir / "capture_performance_baseline.py", capture_args)

    history_output: dict[str, Any] = {}
    comparison_report: dict[str, Any] = {}
    if not args.skip_history:
        history_result = _run_python_script(
            scripts_dir / "record_performance_history.py",
            [
                "--bundle",
                str(baseline_bundle_path),
                "--history-dir",
                args.history_dir,
                "--dashboard",
                args.dashboard,
                *(["--compare-to-latest"] if args.compare_to_latest else []),
            ],
        )
        history_output = json.loads(history_result.stdout)
        comparison_path = history_output.get("comparison_path")
        if comparison_path:
            comparison_report = _read_json(Path(str(comparison_path)))

    report = build_performance_checkpoint_report(
        label=args.label,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        runtime_budget=runtime_budget,
        runtime_summary=runtime_summary,
        route_exercise=route_exercise,
        search_benchmark=search_report,
        comparison_report=comparison_report,
        artifacts={
            "route_exercise": str(route_exercise_path) if route_exercise_path.exists() else "",
            "runtime_budget": str(runtime_budget_path),
            "runtime_summary": str(runtime_summary_path),
            "search_benchmark": str(search_report_path) if search_report_path.exists() else "",
            "baseline_bundle": str(baseline_bundle_path),
            "history_dashboard": str(Path(args.dashboard).resolve()) if not args.skip_history else "",
            "history_manifest": str(Path(args.history_dir).resolve() / "index.json") if not args.skip_history else "",
            "comparison": str(history_output.get("comparison_path") or ""),
        },
    )

    json_report_path = checkpoint_dir / "checkpoint-report.json"
    markdown_report_path = checkpoint_dir / "checkpoint-report.md"
    _write_json(json_report_path, report)
    markdown_report_path.write_text(
        render_performance_checkpoint_markdown(report),
        encoding="utf-8",
    )

    rendered = (
        json.dumps(report, indent=2)
        if args.format == "json"
        else render_performance_checkpoint_markdown(report)
    )
    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    print(rendered)
    if args.fail_on_attention and report.get("status") != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
