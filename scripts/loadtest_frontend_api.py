from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


SEARCH_TERMS = ["load test", "documento", "task", "criticita", "rapportino"]
READ_HEAVY_SCENARIOS: tuple[tuple[str, int], ...] = (
    ("auth.session", 2),
    ("projects.list", 2),
    ("feed.list", 2),
    ("notifications.list", 1),
    ("search.global", 1),
    ("project.overview", 3),
    ("project.tasks", 3),
    ("project.documents", 1),
    ("project.gantt", 1),
    ("assistant.state", 1),
)
MIXED_CRUD_SCENARIOS: tuple[tuple[str, int], ...] = READ_HEAVY_SCENARIOS + (
    ("feed.seen", 2),
    ("task.posts.create", 2),
    ("post.comments.create", 2),
    ("post.delete", 1),
    ("comment.delete", 1),
)


@dataclass
class EndpointStats:
    latencies_ms: list[float] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    status_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    sample_errors: list[str] = field(default_factory=list)


@dataclass
class VirtualUserState:
    email: str
    project_id: int | None = None
    task_id: int | None = None
    cached_post_ids: list[int] = field(default_factory=list)
    created_post_ids: list[int] = field(default_factory=list)
    created_comment_ids: list[int] = field(default_factory=list)


class MetricsCollector:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._per_endpoint: dict[str, EndpointStats] = defaultdict(EndpointStats)
        self._login_failures = 0
        self._bootstrap_failures = 0

    async def record(
        self,
        *,
        endpoint_name: str,
        latency_ms: float,
        status_code: int | None,
        ok: bool,
        error: str | None = None,
    ) -> None:
        async with self._lock:
            stats = self._per_endpoint[endpoint_name]
            stats.latencies_ms.append(latency_ms)
            stats.status_counts[str(status_code or "error")] += 1
            if ok:
                stats.success_count += 1
            else:
                stats.failure_count += 1
                if error and len(stats.sample_errors) < 3:
                    stats.sample_errors.append(error)

    async def record_login_failure(self) -> None:
        async with self._lock:
            self._login_failures += 1

    async def record_bootstrap_failure(self) -> None:
        async with self._lock:
            self._bootstrap_failures += 1

    def summary(self) -> dict[str, Any]:
        endpoint_report: dict[str, Any] = {}
        all_latencies: list[float] = []
        total_requests = 0
        total_failures = 0

        for endpoint_name, stats in self._per_endpoint.items():
            total = stats.success_count + stats.failure_count
            total_requests += total
            total_failures += stats.failure_count
            all_latencies.extend(stats.latencies_ms)
            endpoint_report[endpoint_name] = {
                "requests": total,
                "successes": stats.success_count,
                "failures": stats.failure_count,
                "failure_ratio": round(stats.failure_count / total, 4) if total else 0.0,
                "avg_ms": round(statistics.fmean(stats.latencies_ms), 2) if stats.latencies_ms else 0.0,
                "p50_ms": percentile(stats.latencies_ms, 50),
                "p95_ms": percentile(stats.latencies_ms, 95),
                "p99_ms": percentile(stats.latencies_ms, 99),
                "max_ms": round(max(stats.latencies_ms), 2) if stats.latencies_ms else 0.0,
                "status_counts": dict(stats.status_counts),
                "sample_errors": stats.sample_errors,
            }

        return {
            "total_requests": total_requests,
            "total_failures": total_failures,
            "failure_ratio": round(total_failures / total_requests, 4) if total_requests else 0.0,
            "avg_ms": round(statistics.fmean(all_latencies), 2) if all_latencies else 0.0,
            "p50_ms": percentile(all_latencies, 50),
            "p95_ms": percentile(all_latencies, 95),
            "p99_ms": percentile(all_latencies, 99),
            "max_ms": round(max(all_latencies), 2) if all_latencies else 0.0,
            "login_failures": self._login_failures,
            "bootstrap_failures": self._bootstrap_failures,
            "endpoints": endpoint_report,
        }


def percentile(values: list[float], target_percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    rank = max(0, min(len(ordered) - 1, round((target_percentile / 100) * (len(ordered) - 1))))
    return round(ordered[rank], 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run staged async load tests against frontend API routes.",
    )
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--email-prefix", default="loadtest.user")
    parser.add_argument("--password", default="devpass123")
    parser.add_argument("--profile", choices=("read-heavy", "mixed-crud"), default="read-heavy")
    parser.add_argument("--session-mode", choices=("steady-state", "fresh-login"), default="steady-state")
    parser.add_argument("--stages", default="10,25,50")
    parser.add_argument("--spawn-rate", type=float, default=20.0)
    parser.add_argument("--duration-seconds", type=int, default=20)
    parser.add_argument("--max-failure-ratio", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=800.0)
    parser.add_argument("--project-id", type=int, default=0)
    parser.add_argument("--output", default="")
    parser.add_argument("--stop-on-fail", action="store_true")
    return parser.parse_args()


def choose_scenario(profile: str) -> str:
    scenarios = MIXED_CRUD_SCENARIOS if profile == "mixed-crud" else READ_HEAVY_SCENARIOS
    return random.choices(
        [scenario_name for scenario_name, _weight in scenarios],
        weights=[weight for _scenario_name, weight in scenarios],
        k=1,
    )[0]


async def request_and_record(
    client: httpx.AsyncClient,
    collector: MetricsCollector,
    *,
    endpoint_name: str,
    method: str,
    path: str,
    body: Any = None,
    json_body: Any = None,
    files: Any = None,
    headers: dict[str, str] | None = None,
    success_statuses: set[int] | None = None,
    record_result: bool = True,
) -> tuple[bool, httpx.Response | None]:
    started_at = time.perf_counter()
    status_code: int | None = None
    error_message: str | None = None
    ok = False
    response: httpx.Response | None = None
    expected = success_statuses or {200}

    try:
        response = await client.request(
            method,
            path,
            content=body,
            json=json_body,
            files=files,
            headers=headers,
        )
        status_code = response.status_code
        ok = response.status_code in expected
        if not ok:
            error_message = response.text[:200]
    except Exception as exc:  # pragma: no cover - script level network errors
        error_message = str(exc)

    if record_result:
        await collector.record(
            endpoint_name=endpoint_name,
            latency_ms=(time.perf_counter() - started_at) * 1000,
            status_code=status_code,
            ok=ok,
            error=error_message,
        )
    return ok, response


async def login_user(
    client: httpx.AsyncClient,
    *,
    email: str,
    password: str,
    collector: MetricsCollector,
    record_result: bool = True,
) -> bool:
    ok, _response = await request_and_record(
        client,
        collector,
        endpoint_name="auth.login",
        method="POST",
        path="/api/auth/login",
        json_body={"usernameOrEmail": email, "password": password},
        success_statuses={200},
        record_result=record_result,
    )
    if not ok:
        await collector.record_login_failure()
    return ok


async def resolve_project_id(
    client: httpx.AsyncClient,
    collector: MetricsCollector,
    *,
    preferred_project_id: int,
    record_result: bool = True,
) -> int | None:
    if preferred_project_id > 0:
        return preferred_project_id
    ok, response = await request_and_record(
        client,
        collector,
        endpoint_name="projects.list",
        method="GET",
        path="/api/projects",
        record_result=record_result,
    )
    if not ok or response is None:
        return None
    payload = response.json()
    items = payload if isinstance(payload, list) else payload.get("items") or payload.get("value") or []
    if not isinstance(items, list) or not items:
        return None
    try:
        return int(items[0]["id"])
    except Exception:
        return None


async def refresh_task_id(
    client: httpx.AsyncClient,
    collector: MetricsCollector,
    *,
    state: VirtualUserState,
    record_result: bool = True,
) -> int | None:
    if state.project_id is None:
        return None
    ok, response = await request_and_record(
        client,
        collector,
        endpoint_name="project.tasks",
        method="GET",
        path=f"/api/projects/{state.project_id}/tasks",
        record_result=record_result,
    )
    if not ok or response is None:
        return None
    payload = response.json()
    items = payload if isinstance(payload, list) else payload.get("items") or payload.get("value") or []
    if not isinstance(items, list) or not items:
        return None
    try:
        state.task_id = int(items[0]["id"])
    except Exception:
        state.task_id = None
    return state.task_id


async def refresh_feed_cache(
    client: httpx.AsyncClient,
    collector: MetricsCollector,
    *,
    state: VirtualUserState,
    limit: int = 10,
    record_result: bool = True,
) -> list[int]:
    ok, response = await request_and_record(
        client,
        collector,
        endpoint_name="feed.list",
        method="GET",
        path=f"/api/feed?limit={limit}&offset=0",
        record_result=record_result,
    )
    if not ok or response is None:
        return state.cached_post_ids
    payload = response.json()
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return state.cached_post_ids

    cached_ids: list[int] = []
    for item in items:
        try:
            post_id = int(item["id"])
        except Exception:
            continue
        cached_ids.append(post_id)
    state.cached_post_ids = cached_ids
    return state.cached_post_ids


def build_multipart_payload(text: str, *, post_kind: str | None = None) -> dict[str, tuple[None, str]]:
    payload = {
        "text": (None, text),
        "is_public": (None, "false"),
        "alert": (None, "false"),
    }
    if post_kind:
        payload["post_kind"] = (None, post_kind)
    return payload


async def bootstrap_user_state(
    client: httpx.AsyncClient,
    collector: MetricsCollector,
    *,
    state: VirtualUserState,
    preferred_project_id: int,
    record_result: bool = True,
) -> bool:
    state.project_id = await resolve_project_id(
        client,
        collector,
        preferred_project_id=preferred_project_id,
        record_result=record_result,
    )
    if state.project_id is None:
        return False
    await refresh_task_id(client, collector, state=state, record_result=record_result)
    await refresh_feed_cache(client, collector, state=state, record_result=record_result)
    return True


async def run_scenario(
    client: httpx.AsyncClient,
    collector: MetricsCollector,
    *,
    scenario_name: str,
    state: VirtualUserState,
) -> None:
    if state.project_id is None:
        return

    if scenario_name == "auth.session":
        await request_and_record(
            client,
            collector,
            endpoint_name="auth.session",
            method="GET",
            path="/api/auth/session",
        )
        return

    if scenario_name == "projects.list":
        await resolve_project_id(client, collector, preferred_project_id=state.project_id)
        return

    if scenario_name == "feed.list":
        await refresh_feed_cache(client, collector, state=state)
        return

    if scenario_name == "notifications.list":
        await request_and_record(
            client,
            collector,
            endpoint_name="notifications.list",
            method="GET",
            path="/api/notifications?limit=10",
        )
        return

    if scenario_name == "search.global":
        await request_and_record(
            client,
            collector,
            endpoint_name="search.global",
            method="GET",
            path=f"/api/search/global?q={random.choice(SEARCH_TERMS)}&limit=6",
        )
        return

    if scenario_name == "project.overview":
        await request_and_record(
            client,
            collector,
            endpoint_name="project.overview",
            method="GET",
            path=f"/api/projects/{state.project_id}/overview",
        )
        return

    if scenario_name == "project.tasks":
        await refresh_task_id(client, collector, state=state)
        return

    if scenario_name == "project.documents":
        await request_and_record(
            client,
            collector,
            endpoint_name="project.documents",
            method="GET",
            path=f"/api/projects/{state.project_id}/documents",
        )
        return

    if scenario_name == "project.gantt":
        await request_and_record(
            client,
            collector,
            endpoint_name="project.gantt",
            method="GET",
            path=f"/api/projects/{state.project_id}/gantt",
        )
        return

    if scenario_name == "assistant.state":
        await request_and_record(
            client,
            collector,
            endpoint_name="assistant.state",
            method="GET",
            path=f"/api/projects/{state.project_id}/assistant",
        )
        return

    if scenario_name == "feed.seen":
        if not state.cached_post_ids:
            await refresh_feed_cache(client, collector, state=state)
        post_ids = state.cached_post_ids[: min(len(state.cached_post_ids), 3)]
        if not post_ids:
            await request_and_record(
                client,
                collector,
                endpoint_name="feed.seen",
                method="POST",
                path="/api/feed/seen",
                json_body={"postIds": []},
                success_statuses={200},
            )
            return
        await request_and_record(
            client,
            collector,
            endpoint_name="feed.seen",
            method="POST",
            path="/api/feed/seen",
            json_body={"postIds": post_ids},
            success_statuses={200},
        )
        return

    if scenario_name == "task.posts.create":
        if state.task_id is None:
            await refresh_task_id(client, collector, state=state)
        if state.task_id is None:
            return
        ok, response = await request_and_record(
            client,
            collector,
            endpoint_name="task.posts.create",
            method="POST",
            path=f"/api/tasks/{state.task_id}/posts",
            files=build_multipart_payload(
                f"[loadtest] aggiornamento operativo {time.time():.6f}",
                post_kind="work-progress",
            ),
            success_statuses={201},
        )
        if not ok or response is None:
            return
        payload = response.json()
        post_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(post_id, int):
            state.created_post_ids.append(post_id)
            state.cached_post_ids = [post_id, *[value for value in state.cached_post_ids if value != post_id]]
        return

    if scenario_name == "post.comments.create":
        target_post_id: int | None = None
        if state.created_post_ids:
            target_post_id = state.created_post_ids[-1]
        elif state.cached_post_ids:
            target_post_id = state.cached_post_ids[0]
        else:
            await refresh_feed_cache(client, collector, state=state)
            if state.cached_post_ids:
                target_post_id = state.cached_post_ids[0]
        if target_post_id is None:
            return
        ok, response = await request_and_record(
            client,
            collector,
            endpoint_name="post.comments.create",
            method="POST",
            path=f"/api/posts/{target_post_id}/comments",
            files=build_multipart_payload(f"[loadtest] commento {time.time():.6f}"),
            success_statuses={201},
        )
        if not ok or response is None:
            return
        payload = response.json()
        comment_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(comment_id, int):
            state.created_comment_ids.append(comment_id)
        return

    if scenario_name == "post.delete":
        if not state.created_post_ids:
            await run_scenario(client, collector, scenario_name="task.posts.create", state=state)
            return
        post_id = state.created_post_ids.pop()
        ok, _response = await request_and_record(
            client,
            collector,
            endpoint_name="post.delete",
            method="DELETE",
            path=f"/api/posts/{post_id}",
            success_statuses={204},
        )
        if not ok:
            state.created_post_ids.append(post_id)
        else:
            state.cached_post_ids = [value for value in state.cached_post_ids if value != post_id]
        return

    if scenario_name == "comment.delete":
        if not state.created_comment_ids:
            await run_scenario(client, collector, scenario_name="post.comments.create", state=state)
            return
        comment_id = state.created_comment_ids.pop()
        ok, _response = await request_and_record(
            client,
            collector,
            endpoint_name="comment.delete",
            method="DELETE",
            path=f"/api/comments/{comment_id}",
            success_statuses={204},
        )
        if not ok:
            state.created_comment_ids.append(comment_id)
        return

    raise ValueError(f"Scenario non supportato: {scenario_name}")


async def cleanup_virtual_user(
    client: httpx.AsyncClient,
    collector: MetricsCollector,
    *,
    state: VirtualUserState,
) -> None:
    while state.created_comment_ids:
        comment_id = state.created_comment_ids.pop()
        await request_and_record(
            client,
            collector,
            endpoint_name="comment.delete",
            method="DELETE",
            path=f"/api/comments/{comment_id}",
            success_statuses={204},
        )

    while state.created_post_ids:
        post_id = state.created_post_ids.pop()
        await request_and_record(
            client,
            collector,
            endpoint_name="post.delete",
            method="DELETE",
            path=f"/api/posts/{post_id}",
            success_statuses={204},
        )


async def run_virtual_user(
    *,
    user_index: int,
    base_url: str,
    email_prefix: str,
    password: str,
    preferred_project_id: int,
    collector: MetricsCollector,
    deadline: float,
    measurement_start: float,
    start_delay: float,
    profile: str,
    session_mode: str,
) -> None:
    await asyncio.sleep(max(0.0, start_delay))
    state = VirtualUserState(email=f"{email_prefix}.{user_index:04d}@example.com")
    timeout = httpx.Timeout(20.0, connect=10.0)
    limits = httpx.Limits(max_keepalive_connections=4, max_connections=10)

    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=timeout,
        limits=limits,
        follow_redirects=False,
    ) as client:
        record_bootstrap = session_mode == "fresh-login"
        if not await login_user(
            client,
            email=state.email,
            password=password,
            collector=collector,
            record_result=record_bootstrap,
        ):
            await collector.record_bootstrap_failure()
            return

        if not await bootstrap_user_state(
            client,
            collector,
            state=state,
            preferred_project_id=preferred_project_id,
            record_result=record_bootstrap,
        ):
            await collector.record_bootstrap_failure()
            return

        if session_mode == "steady-state" and time.perf_counter() < measurement_start:
            await asyncio.sleep(measurement_start - time.perf_counter())

        while time.perf_counter() < deadline:
            scenario_name = choose_scenario(profile)
            await run_scenario(
                client,
                collector,
                scenario_name=scenario_name,
                state=state,
            )
            await asyncio.sleep(random.uniform(0.35, 1.2))

        if profile == "mixed-crud":
            await cleanup_virtual_user(client, collector, state=state)


async def run_stage(*, stage_users: int, args: argparse.Namespace) -> dict[str, Any]:
    collector = MetricsCollector()
    started_at = time.perf_counter()
    ramp_seconds = stage_users / max(args.spawn_rate, 1.0)
    measurement_start = started_at + ramp_seconds + (0.5 if args.session_mode == "steady-state" else 0.0)
    deadline = measurement_start + args.duration_seconds

    tasks = [
        asyncio.create_task(
            run_virtual_user(
                user_index=index,
                base_url=args.base_url,
                email_prefix=args.email_prefix,
                password=args.password,
                preferred_project_id=args.project_id,
                collector=collector,
                deadline=deadline,
                measurement_start=measurement_start,
                start_delay=(index - 1) / max(args.spawn_rate, 1.0),
                profile=args.profile,
                session_mode=args.session_mode,
            )
        )
        for index in range(1, stage_users + 1)
    ]
    await asyncio.gather(*tasks)
    summary = collector.summary()
    summary["profile"] = args.profile
    summary["session_mode"] = args.session_mode
    summary["users"] = stage_users
    summary["duration_seconds"] = round(time.perf_counter() - started_at, 2)
    summary["pass"] = (
        summary["failure_ratio"] <= args.max_failure_ratio
        and summary["p95_ms"] <= args.max_p95_ms
        and summary["login_failures"] == 0
        and summary["bootstrap_failures"] == 0
    )
    return summary


async def main_async() -> int:
    args = parse_args()
    stages = [int(value.strip()) for value in args.stages.split(",") if value.strip()]
    if not stages:
        raise SystemExit("Specifica almeno uno stage con --stages.")

    report: dict[str, Any] = {
        "base_url": args.base_url,
        "profile": args.profile,
        "session_mode": args.session_mode,
        "project_id": args.project_id or None,
        "spawn_rate": args.spawn_rate,
        "duration_seconds": args.duration_seconds,
        "max_failure_ratio": args.max_failure_ratio,
        "max_p95_ms": args.max_p95_ms,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stages": [],
    }

    for stage_users in stages:
        print(
            f"[loadtest] running {args.profile} stage with {stage_users} virtual users "
            f"({args.session_mode})..."
        )
        stage_summary = await run_stage(stage_users=stage_users, args=args)
        report["stages"].append(stage_summary)
        print(
            json.dumps(
                {
                    "profile": stage_summary["profile"],
                    "session_mode": stage_summary["session_mode"],
                    "users": stage_summary["users"],
                    "requests": stage_summary["total_requests"],
                    "failure_ratio": stage_summary["failure_ratio"],
                    "p95_ms": stage_summary["p95_ms"],
                    "pass": stage_summary["pass"],
                }
            )
        )
        if args.stop_on_fail and not stage_summary["pass"]:
            break

    report["breaking_stage"] = next(
        (stage["users"] for stage in report["stages"] if not stage["pass"]),
        None,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0 if report["breaking_stage"] is None else 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
