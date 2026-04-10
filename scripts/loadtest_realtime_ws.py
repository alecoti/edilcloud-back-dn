from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import websockets


@dataclass
class ListenerConnection:
    email: str
    client: httpx.AsyncClient
    websocket: websockets.ClientConnection
    queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    reader_task: asyncio.Task[None] | None = None


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
        description="Benchmark the websocket fanout lag of the project realtime channel.",
    )
    parser.add_argument("--base-url", default="http://localhost:3000")
    parser.add_argument("--email-prefix", default="loadtest.user")
    parser.add_argument("--owner-email", default="loadtest.user.owner@example.com")
    parser.add_argument("--password", default="devpass123")
    parser.add_argument("--project-id", type=int, default=0)
    parser.add_argument("--stages", default="5,10")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--event-timeout", type=float, default=8.0)
    parser.add_argument("--max-delivery-loss", type=float, default=0.01)
    parser.add_argument("--max-p95-lag-ms", type=float, default=1200.0)
    parser.add_argument("--output", default="")
    parser.add_argument("--stop-on-fail", action="store_true")
    return parser.parse_args()


async def login(client: httpx.AsyncClient, *, email: str, password: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"usernameOrEmail": email, "password": password},
    )
    if response.status_code != 200:
        raise RuntimeError(f"Login fallito per {email}: {response.status_code} {response.text[:180]}")


async def resolve_project_id(client: httpx.AsyncClient, preferred_project_id: int) -> int:
    if preferred_project_id > 0:
        return preferred_project_id
    response = await client.get("/api/projects")
    if response.status_code != 200:
        raise RuntimeError(f"Impossibile leggere i progetti: {response.status_code} {response.text[:180]}")
    payload = response.json()
    items = payload if isinstance(payload, list) else payload.get("items") or payload.get("value") or []
    if not isinstance(items, list) or not items:
        raise RuntimeError("Nessun progetto disponibile per il benchmark realtime.")
    try:
        return int(items[0]["id"])
    except Exception as exc:  # pragma: no cover - defensive for ad-hoc scripts
        raise RuntimeError("Payload progetti non valido per il benchmark realtime.") from exc


async def resolve_task_id(client: httpx.AsyncClient, project_id: int) -> int:
    response = await client.get(f"/api/projects/{project_id}/tasks")
    if response.status_code != 200:
        raise RuntimeError(f"Impossibile leggere i task progetto {project_id}: {response.status_code}")
    payload = response.json()
    items = payload if isinstance(payload, list) else payload.get("items") or payload.get("value") or []
    if not isinstance(items, list) or not items:
        raise RuntimeError("Nessun task disponibile per il benchmark realtime.")
    try:
        return int(items[0]["id"])
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Payload task non valido per il benchmark realtime.") from exc


async def resolve_project_socket_url(client: httpx.AsyncClient, project_id: int) -> str:
    response = await client.get(f"/api/projects/{project_id}/realtime/session")
    if response.status_code != 200:
        raise RuntimeError(
            f"Impossibile inizializzare la sessione realtime progetto {project_id}: {response.status_code}"
        )
    payload = response.json()
    socket = payload.get("project") if isinstance(payload, dict) else None
    url = socket.get("url") if isinstance(socket, dict) else None
    if not isinstance(url, str) or not url:
        raise RuntimeError("Sessione realtime progetto senza URL websocket valida.")
    return url


async def websocket_reader(connection: ListenerConnection) -> None:
    try:
        async for raw_message in connection.websocket:
            try:
                payload = json.loads(raw_message)
            except json.JSONDecodeError:
                continue
            await connection.queue.put(payload)
    except Exception:
        pass
    finally:
        await connection.queue.put(None)


async def open_listener(
    *,
    base_url: str,
    email: str,
    password: str,
    project_id: int,
    connect_timeout: float,
) -> ListenerConnection:
    client = httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
    )
    await login(client, email=email, password=password)
    websocket_url = await resolve_project_socket_url(client, project_id)
    websocket = await websockets.connect(
        websocket_url,
        open_timeout=connect_timeout,
        ping_interval=20,
        ping_timeout=20,
        max_size=2**20,
    )
    connection = ListenerConnection(email=email, client=client, websocket=websocket)
    connection.reader_task = asyncio.create_task(websocket_reader(connection))
    return connection


async def close_listener(connection: ListenerConnection) -> None:
    if connection.reader_task is not None:
        connection.reader_task.cancel()
        try:
            await connection.reader_task
        except asyncio.CancelledError:
            pass
    try:
        await connection.websocket.close()
    finally:
        await connection.client.aclose()


async def wait_for_post_event(
    connection: ListenerConnection,
    *,
    post_id: int,
    timeout_seconds: float,
) -> float | None:
    deadline = time.perf_counter() + timeout_seconds
    while time.perf_counter() < deadline:
        remaining = deadline - time.perf_counter()
        try:
            payload = await asyncio.wait_for(connection.queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            return None
        if payload is None:
            return None
        if payload.get("type") == "post.created" and payload.get("postId") == post_id:
            return time.perf_counter()
    return None


async def create_round_trip_post(
    publisher_client: httpx.AsyncClient,
    *,
    task_id: int,
    round_index: int,
) -> tuple[int, float, float]:
    started_at = time.perf_counter()
    response = await publisher_client.post(
        f"/api/tasks/{task_id}/posts",
        files={
            "text": (None, f"[realtime-loadtest] round {round_index} {time.time():.6f}"),
            "post_kind": (None, "work-progress"),
            "is_public": (None, "false"),
            "alert": (None, "false"),
        },
    )
    finished_at = time.perf_counter()
    if response.status_code != 201:
        raise RuntimeError(
            f"Creazione post realtime fallita: {response.status_code} {response.text[:180]}"
        )
    payload = response.json()
    post_id = payload.get("id") if isinstance(payload, dict) else None
    if not isinstance(post_id, int):
        raise RuntimeError("Risposta creazione post senza id valido.")
    return post_id, started_at, finished_at


async def delete_post(publisher_client: httpx.AsyncClient, *, post_id: int) -> None:
    response = await publisher_client.delete(f"/api/posts/{post_id}")
    if response.status_code not in {204, 404}:
        raise RuntimeError(f"Cleanup post {post_id} fallito: {response.status_code} {response.text[:180]}")


async def run_stage(stage_users: int, args: argparse.Namespace) -> dict[str, Any]:
    project_id: int | None = None
    owner_client = httpx.AsyncClient(
        base_url=args.base_url,
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=False,
    )
    listeners: list[ListenerConnection] = []
    connect_failures: list[str] = []
    publish_latencies_ms: list[float] = []
    delivery_lag_ms: list[float] = []
    deliveries_expected = 0
    deliveries_received = 0
    rounds_executed = 0

    try:
        await login(owner_client, email=args.owner_email, password=args.password)
        project_id = await resolve_project_id(owner_client, args.project_id)
        task_id = await resolve_task_id(owner_client, project_id)

        for user_index in range(1, stage_users + 1):
            email = f"{args.email_prefix}.{user_index:04d}@example.com"
            try:
                connection = await open_listener(
                    base_url=args.base_url,
                    email=email,
                    password=args.password,
                    project_id=project_id,
                    connect_timeout=args.connect_timeout,
                )
                listeners.append(connection)
            except Exception as exc:  # pragma: no cover - script level diagnostics
                connect_failures.append(f"{email}: {exc}")

        if not listeners:
            raise RuntimeError("Nessuna connessione realtime aperta con successo.")

        for round_index in range(1, args.rounds + 1):
            post_id, publish_started_at, publish_finished_at = await create_round_trip_post(
                owner_client,
                task_id=task_id,
                round_index=round_index,
            )
            publish_latencies_ms.append((publish_finished_at - publish_started_at) * 1000)
            rounds_executed += 1
            deliveries_expected += len(listeners)

            received_times = await asyncio.gather(
                *[
                    wait_for_post_event(
                        listener,
                        post_id=post_id,
                        timeout_seconds=args.event_timeout,
                    )
                    for listener in listeners
                ]
            )

            for received_at in received_times:
                if received_at is None:
                    continue
                deliveries_received += 1
                delivery_lag_ms.append((received_at - publish_started_at) * 1000)

            await delete_post(owner_client, post_id=post_id)

    finally:
        for listener in listeners:
            await close_listener(listener)
        await owner_client.aclose()

    delivery_ratio = (
        round(deliveries_received / deliveries_expected, 4) if deliveries_expected else 0.0
    )
    summary = {
        "users": stage_users,
        "project_id": project_id,
        "connected": len(listeners),
        "connection_failures": connect_failures,
        "rounds": rounds_executed,
        "publish_requests": len(publish_latencies_ms),
        "publish_avg_ms": round(statistics.fmean(publish_latencies_ms), 2)
        if publish_latencies_ms
        else 0.0,
        "publish_p95_ms": percentile(publish_latencies_ms, 95),
        "delivery_expected": deliveries_expected,
        "delivery_received": deliveries_received,
        "delivery_ratio": delivery_ratio,
        "delivery_loss_ratio": round(1 - delivery_ratio, 4) if deliveries_expected else 1.0,
        "lag_p50_ms": percentile(delivery_lag_ms, 50),
        "lag_p95_ms": percentile(delivery_lag_ms, 95),
        "lag_p99_ms": percentile(delivery_lag_ms, 99),
        "lag_max_ms": round(max(delivery_lag_ms), 2) if delivery_lag_ms else 0.0,
    }
    summary["pass"] = (
        not connect_failures
        and summary["delivery_loss_ratio"] <= args.max_delivery_loss
        and summary["lag_p95_ms"] <= args.max_p95_lag_ms
    )
    return summary


async def main_async() -> int:
    args = parse_args()
    stages = [int(value.strip()) for value in args.stages.split(",") if value.strip()]
    if not stages:
        raise SystemExit("Specifica almeno uno stage con --stages.")

    report: dict[str, Any] = {
        "base_url": args.base_url,
        "project_id": args.project_id or None,
        "rounds": args.rounds,
        "connect_timeout": args.connect_timeout,
        "event_timeout": args.event_timeout,
        "max_delivery_loss": args.max_delivery_loss,
        "max_p95_lag_ms": args.max_p95_lag_ms,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "stages": [],
    }

    for stage_users in stages:
        print(f"[realtime-loadtest] running stage with {stage_users} websocket listeners...")
        stage_summary = await run_stage(stage_users, args)
        report["stages"].append(stage_summary)
        print(
            json.dumps(
                {
                    "users": stage_summary["users"],
                    "connected": stage_summary["connected"],
                    "delivery_ratio": stage_summary["delivery_ratio"],
                    "lag_p95_ms": stage_summary["lag_p95_ms"],
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
