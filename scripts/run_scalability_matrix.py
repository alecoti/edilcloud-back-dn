from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from edilcloud.platform.performance_matrix import (
    build_scalability_matrix_report,
    render_scalability_matrix_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the dev scalability matrix across read-heavy, auth burst, mixed CRUD and realtime scenarios.",
    )
    parser.add_argument("--label", default="local-dev-matrix")
    parser.add_argument("--frontend-base-url", default="http://localhost:3000")
    parser.add_argument("--backend-base-url", default="http://localhost:8001")
    parser.add_argument("--email", default="project.detail.owner@example.com")
    parser.add_argument("--owner-email", default="loadtest.user.owner@example.com")
    parser.add_argument("--password", default="devpass123")
    parser.add_argument("--email-prefix", default="loadtest.user")
    parser.add_argument("--project-id", type=int, default=0)
    parser.add_argument("--read-heavy-stages", default="10,25,50")
    parser.add_argument("--auth-burst-stages", default="10,25,50")
    parser.add_argument("--mixed-crud-stages", default="5,10,25")
    parser.add_argument("--realtime-stages", default="5,10,25")
    parser.add_argument("--read-heavy-duration-seconds", type=int, default=20)
    parser.add_argument("--auth-burst-duration-seconds", type=int, default=15)
    parser.add_argument("--mixed-crud-duration-seconds", type=int, default=30)
    parser.add_argument("--read-heavy-spawn-rate", type=float, default=20.0)
    parser.add_argument("--auth-burst-spawn-rate", type=float, default=50.0)
    parser.add_argument("--mixed-crud-spawn-rate", type=float, default=15.0)
    parser.add_argument("--realtime-rounds", type=int, default=2)
    parser.add_argument("--history-dir", default="docs/performance-history")
    parser.add_argument("--dashboard", default="docs/PERFORMANCE_HISTORY.md")
    parser.add_argument("--work-dir", default=".tmp/scalability-matrix")
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--skip-history", action="store_true")
    parser.add_argument("--compare-to-latest", action="store_true")
    parser.add_argument("--stop-on-fail", action="store_true")
    parser.add_argument("--fail-on-attention", action="store_true")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _run_python_script(
    script_path: Path,
    args: list[str],
    *,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and not allow_failure:
        raise subprocess.CalledProcessError(
            result.returncode,
            [sys.executable, str(script_path), *args],
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _load_artifact(path: Path, *, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeError(
            "Lo script non ha prodotto l'artifact atteso `{path}`. stdout={stdout!r} stderr={stderr!r}".format(
                path=path,
                stdout=result.stdout[-500:],
                stderr=result.stderr[-500:],
            )
        )
    return _read_json(path)


def main() -> int:
    args = parse_args()
    scripts_dir = Path(__file__).resolve().parent
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    work_root = Path(args.work_dir).resolve()
    run_dir = work_root / f"{timestamp}--{args.label}"
    run_dir.mkdir(parents=True, exist_ok=True)

    search_path = run_dir / "search-benchmark.json"
    read_heavy_path = run_dir / "read-heavy.json"
    auth_burst_path = run_dir / "auth-burst.json"
    mixed_crud_path = run_dir / "mixed-crud.json"
    realtime_path = run_dir / "realtime.json"
    baseline_bundle_path = run_dir / "baseline-bundle.json"
    report_json_path = run_dir / "scalability-matrix.json"
    report_md_path = run_dir / "scalability-matrix.md"

    search_report: dict[str, Any] = {}
    if not args.skip_search:
        search_result = _run_python_script(
            scripts_dir / "benchmark_search_global.py",
            [
                "--base-url",
                args.frontend_base_url,
                "--email",
                args.email,
                "--password",
                args.password,
                "--format",
                "json",
                "--output",
                str(search_path),
            ],
        )
        search_report = _load_artifact(search_path, result=search_result)

    read_heavy_result = _run_python_script(
        scripts_dir / "loadtest_frontend_api.py",
        [
            "--base-url",
            args.frontend_base_url,
            "--email-prefix",
            args.email_prefix,
            "--password",
            args.password,
            "--profile",
            "read-heavy",
            "--session-mode",
            "steady-state",
            "--stages",
            args.read_heavy_stages,
            "--spawn-rate",
            str(args.read_heavy_spawn_rate),
            "--duration-seconds",
            str(args.read_heavy_duration_seconds),
            "--project-id",
            str(args.project_id),
            "--output",
            str(read_heavy_path),
            *(["--stop-on-fail"] if args.stop_on_fail else []),
        ],
        allow_failure=True,
    )
    read_heavy_report = _load_artifact(read_heavy_path, result=read_heavy_result)

    auth_burst_result = _run_python_script(
        scripts_dir / "loadtest_frontend_api.py",
        [
            "--base-url",
            args.frontend_base_url,
            "--email-prefix",
            args.email_prefix,
            "--password",
            args.password,
            "--profile",
            "read-heavy",
            "--session-mode",
            "fresh-login",
            "--stages",
            args.auth_burst_stages,
            "--spawn-rate",
            str(args.auth_burst_spawn_rate),
            "--duration-seconds",
            str(args.auth_burst_duration_seconds),
            "--project-id",
            str(args.project_id),
            "--output",
            str(auth_burst_path),
            *(["--stop-on-fail"] if args.stop_on_fail else []),
        ],
        allow_failure=True,
    )
    auth_burst_report = _load_artifact(auth_burst_path, result=auth_burst_result)

    mixed_crud_result = _run_python_script(
        scripts_dir / "loadtest_frontend_api.py",
        [
            "--base-url",
            args.frontend_base_url,
            "--email-prefix",
            args.email_prefix,
            "--password",
            args.password,
            "--profile",
            "mixed-crud",
            "--session-mode",
            "steady-state",
            "--stages",
            args.mixed_crud_stages,
            "--spawn-rate",
            str(args.mixed_crud_spawn_rate),
            "--duration-seconds",
            str(args.mixed_crud_duration_seconds),
            "--project-id",
            str(args.project_id),
            "--output",
            str(mixed_crud_path),
            *(["--stop-on-fail"] if args.stop_on_fail else []),
        ],
        allow_failure=True,
    )
    mixed_crud_report = _load_artifact(mixed_crud_path, result=mixed_crud_result)

    realtime_result = _run_python_script(
        scripts_dir / "loadtest_realtime_ws.py",
        [
            "--base-url",
            args.frontend_base_url,
            "--email-prefix",
            args.email_prefix,
            "--owner-email",
            args.owner_email,
            "--password",
            args.password,
            "--project-id",
            str(args.project_id),
            "--stages",
            args.realtime_stages,
            "--rounds",
            str(args.realtime_rounds),
            "--output",
            str(realtime_path),
            *(["--stop-on-fail"] if args.stop_on_fail else []),
        ],
        allow_failure=True,
    )
    realtime_report = _load_artifact(realtime_path, result=realtime_result)

    capture_args = [
        "--kind",
        "scalability-matrix",
        "--base-url",
        args.backend_base_url,
        "--label",
        args.label,
        "--read-heavy-report",
        str(read_heavy_path),
        "--auth-burst-report",
        str(auth_burst_path),
        "--mixed-crud-report",
        str(mixed_crud_path),
        "--realtime-report",
        str(realtime_path),
        "--output",
        str(baseline_bundle_path),
    ]
    if search_path.exists():
        capture_args.extend(["--search-benchmark-report", str(search_path)])
    _run_python_script(scripts_dir / "capture_performance_baseline.py", capture_args)
    baseline_bundle = _read_json(baseline_bundle_path)

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

    report = build_scalability_matrix_report(
        label=args.label,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        runtime_budget=baseline_bundle.get("runtime_budget", {}) if isinstance(baseline_bundle, dict) else {},
        read_heavy=read_heavy_report,
        auth_burst=auth_burst_report,
        mixed_crud=mixed_crud_report,
        realtime=realtime_report,
        search_benchmark=search_report,
        comparison_report=comparison_report,
        artifacts={
            "read_heavy": str(read_heavy_path),
            "auth_burst": str(auth_burst_path),
            "mixed_crud": str(mixed_crud_path),
            "realtime": str(realtime_path),
            "search_benchmark": str(search_path) if search_path.exists() else "",
            "baseline_bundle": str(baseline_bundle_path),
        },
    )
    _write_json(report_json_path, report)
    report_md_path.write_text(render_scalability_matrix_markdown(report), encoding="utf-8")

    output_text = (
        json.dumps(report, indent=2)
        if args.format == "json"
        else render_scalability_matrix_markdown(report)
    )

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")

    print(output_text)
    status = str(report.get("status") or "unknown")
    if status == "fail":
        return 1
    if args.fail_on_attention and status != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
