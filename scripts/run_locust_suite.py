from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


USER_CLASSES = {
    "auth-burst": "AuthBurstUser",
    "mixed-crud": "MixedCrudUser",
    "read-heavy": "ReadHeavyUser",
}
SHAPE_CLASSES = {
    "soak": "SoakShape",
    "spike": "SpikeShape",
    "step": "StepLoadShape",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a normalized Locust suite and publish a Test Center JSON artifact.",
    )
    parser.add_argument("--host", default="http://localhost:3000")
    parser.add_argument("--profile", choices=tuple(USER_CLASSES), default="read-heavy")
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--spawn-rate", type=float, default=5.0)
    parser.add_argument("--run-time", default="2m")
    parser.add_argument("--shape", choices=tuple(SHAPE_CLASSES), default="")
    parser.add_argument("--email-prefix", default="loadtest.user")
    parser.add_argument("--password", default=os.environ.get("EDILCLOUD_LOADTEST_PASSWORD", "devpass123"))
    parser.add_argument("--project-id", type=int, default=0)
    parser.add_argument("--search-terms", default="load test,documento,task,criticita,rapportino")
    parser.add_argument("--max-failure-ratio", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1200.0)
    parser.add_argument("--output-dir", default=".tmp/test-center/loadtests")
    parser.add_argument("--fail-on-threshold", action="store_true")
    return parser.parse_args()


def _float_value(value: str | None) -> float:
    try:
        return float(value or 0)
    except ValueError:
        return 0.0


def _int_value(value: str | None) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def _normalize_stats_rows(rows: list[dict[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    endpoints: list[dict[str, Any]] = []
    aggregate_row: dict[str, str] | None = None
    for row in rows:
        if row.get("Name") == "Aggregated":
            aggregate_row = row
            continue
        endpoints.append(
            {
                "method": row.get("Type", ""),
                "name": row.get("Name", ""),
                "requests": _int_value(row.get("Request Count")),
                "failures": _int_value(row.get("Failure Count")),
                "avg_ms": _float_value(row.get("Average Response Time")),
                "p50_ms": _float_value(row.get("50%")),
                "p95_ms": _float_value(row.get("95%")),
                "p99_ms": _float_value(row.get("99%")),
                "max_ms": _float_value(row.get("Max Response Time")),
                "requests_per_second": _float_value(row.get("Requests/s")),
                "failures_per_second": _float_value(row.get("Failures/s")),
            }
        )

    aggregate = aggregate_row or {}
    requests = _int_value(aggregate.get("Request Count"))
    failures = _int_value(aggregate.get("Failure Count"))
    return {
        "requests": requests,
        "failures": failures,
        "failure_ratio": round(failures / requests, 4) if requests else 0.0,
        "avg_ms": _float_value(aggregate.get("Average Response Time")),
        "p50_ms": _float_value(aggregate.get("50%")),
        "p95_ms": _float_value(aggregate.get("95%")),
        "p99_ms": _float_value(aggregate.get("99%")),
        "max_ms": _float_value(aggregate.get("Max Response Time")),
        "requests_per_second": _float_value(aggregate.get("Requests/s")),
        "failures_per_second": _float_value(aggregate.get("Failures/s")),
    }, endpoints


def _read_failures(path: Path) -> list[dict[str, str]]:
    return _read_csv_rows(path)


def _build_command(args: argparse.Namespace, csv_prefix: Path, html_path: Path) -> list[str]:
    locustfile = Path("loadtests/locust/locustfile.py")
    command = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(locustfile),
        "--host",
        args.host,
        "--headless",
        "--users",
        str(args.users),
        "--spawn-rate",
        str(args.spawn_rate),
        "--run-time",
        args.run_time,
        "--csv",
        str(csv_prefix),
        "--html",
        str(html_path),
        "--only-summary",
        USER_CLASSES[args.profile],
    ]
    return command


def main() -> int:
    args = parse_args()
    started_at = time.time()
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(started_at))
    output_dir = Path(args.output_dir).resolve() / f"{timestamp}--locust-{args.profile}"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_prefix = output_dir / "locust"
    html_path = output_dir / "locust-report.html"
    json_path = output_dir / "locust-report.json"

    env = os.environ.copy()
    env["EDILCLOUD_LOADTEST_EMAIL_PREFIX"] = args.email_prefix
    env["EDILCLOUD_LOADTEST_PASSWORD"] = args.password
    env["EDILCLOUD_LOADTEST_PROJECT_ID"] = str(args.project_id)
    env["EDILCLOUD_LOADTEST_SEARCH_TERMS"] = args.search_terms
    env["EDILCLOUD_LOADTEST_SHAPE"] = args.shape

    command = _build_command(args, csv_prefix, html_path)
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    stats_rows = _read_csv_rows(Path(f"{csv_prefix}_stats.csv"))
    overall, endpoints = _normalize_stats_rows(stats_rows)
    failures = _read_failures(Path(f"{csv_prefix}_failures.csv"))
    threshold_pass = (
        overall["requests"] > 0
        and overall["failure_ratio"] <= args.max_failure_ratio
        and overall["p95_ms"] <= args.max_p95_ms
    )
    status = "pass" if completed.returncode == 0 and threshold_pass else "fail"
    focus: list[str] = []
    if overall["requests"] <= 0:
        focus.append("Locust non ha prodotto richieste aggregate.")
    if overall["failure_ratio"] > args.max_failure_ratio:
        focus.append(
            "Failure ratio {actual} sopra soglia {limit}.".format(
                actual=overall["failure_ratio"],
                limit=args.max_failure_ratio,
            )
        )
    if overall["p95_ms"] > args.max_p95_ms:
        focus.append(
            "p95 {actual} ms sopra soglia {limit} ms.".format(
                actual=overall["p95_ms"],
                limit=args.max_p95_ms,
            )
        )
    if completed.returncode != 0:
        focus.append(f"Processo Locust terminato con exit code {completed.returncode}.")

    report = {
        "engine": "locust",
        "status": status,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host": args.host,
        "profile": args.profile,
        "user_class": USER_CLASSES[args.profile],
        "shape": args.shape or None,
        "users": args.users,
        "spawn_rate": args.spawn_rate,
        "run_time": args.run_time,
        "duration_seconds": round(time.time() - started_at, 2),
        "scenario": {
            "email_prefix": args.email_prefix,
            "project_id": args.project_id or None,
            "search_terms": [
                term.strip()
                for term in args.search_terms.split(",")
                if term.strip()
            ],
        },
        "thresholds": {
            "max_failure_ratio": args.max_failure_ratio,
            "max_p95_ms": args.max_p95_ms,
        },
        "overall": overall,
        "endpoints": endpoints,
        "failures": failures[:20],
        "focus": focus,
        "artifacts": {
            "json": str(json_path),
            "html": str(html_path),
            "stats_csv": str(csv_prefix) + "_stats.csv",
            "failures_csv": str(csv_prefix) + "_failures.csv",
            "exceptions_csv": str(csv_prefix) + "_exceptions.csv",
        },
        "process": {
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        },
    }
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if status != "pass" and args.fail_on_threshold:
        return 1
    return 0 if completed.returncode == 0 else completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
