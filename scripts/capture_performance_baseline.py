from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx

from edilcloud.platform.performance_baseline import build_performance_baseline_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture a reusable performance baseline bundle from runtime endpoints and optional loadtest reports.",
    )
    parser.add_argument("--kind", default="generic")
    parser.add_argument("--label", default="local-dev")
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--runtime-budget-path", default="/api/v1/health/metrics/budget")
    parser.add_argument("--runtime-summary-path", default="/api/v1/health/metrics/summary")
    parser.add_argument("--read-heavy-report", default="")
    parser.add_argument("--auth-burst-report", default="")
    parser.add_argument("--mixed-crud-report", default="")
    parser.add_argument("--realtime-report", default="")
    parser.add_argument("--search-benchmark-report", default="")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _read_json(path_value: str) -> dict[str, Any]:
    if not path_value:
        return {}
    return json.loads(Path(path_value).read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    with httpx.Client(base_url=args.base_url, timeout=20.0) as client:
        runtime_budget = client.get(args.runtime_budget_path).json()
        runtime_summary = client.get(args.runtime_summary_path).json()

    bundle = build_performance_baseline_bundle(
        kind=args.kind,
        label=args.label,
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        runtime_budget=runtime_budget,
        runtime_summary=runtime_summary,
        read_heavy=_read_json(args.read_heavy_report),
        auth_burst=_read_json(args.auth_burst_report),
        mixed_crud=_read_json(args.mixed_crud_report),
        realtime=_read_json(args.realtime_report),
        search_benchmark=_read_json(args.search_benchmark_report),
    )

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "label": args.label}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
