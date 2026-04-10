from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch runtime performance budget evaluation and render a compact report.",
    )
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--path", default="/api/v1/health/metrics/budget")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", default="")
    parser.add_argument("--fail-on-breached", action="store_true")
    return parser.parse_args()


def render_markdown(payload: dict[str, Any]) -> str:
    budget = payload.get("budget") if isinstance(payload, dict) else {}
    lines = [
        "# Runtime Performance Budget",
        "",
        f"- Status: `{budget.get('status', 'unknown')}`",
        f"- Score: `{budget.get('score_percent', 0)}%`",
        f"- Passing rules: `{budget.get('passing_rules', 0)}`",
        f"- Failing rules: `{budget.get('failing_rules', 0)}`",
        f"- No data rules: `{budget.get('no_data_rules', 0)}`",
        "",
        "## Rules",
        "",
        "| Rule | Status | Requests | p95 ms | Budget p95 ms | Error ratio | Budget error ratio |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    for item in budget.get("rules", []):
        lines.append(
            "| {key} | `{status}` | {requests} | {p95_ms} | {max_p95_ms} | {error_ratio} | {max_error_ratio} |".format(
                key=item.get("key", "-"),
                status=item.get("status", "unknown"),
                requests=item.get("requests", 0),
                p95_ms=item.get("p95_ms", 0),
                max_p95_ms=item.get("max_p95_ms", 0),
                error_ratio=item.get("error_ratio", 0),
                max_error_ratio=item.get("max_error_ratio", 0),
            )
        )

    failing = budget.get("failing", [])
    if failing:
        lines.extend(
            [
                "",
                "## Breached",
                "",
            ]
        )
        for item in failing:
            lines.append(
                "- `{key}` fuori budget: p95 `{p95_ms} ms` su budget `{max_p95_ms} ms`, error ratio `{error_ratio}`".format(
                    key=item.get("key", "-"),
                    p95_ms=item.get("p95_ms", 0),
                    max_p95_ms=item.get("max_p95_ms", 0),
                    error_ratio=item.get("error_ratio", 0),
                )
            )

    missing = budget.get("missing_data", [])
    if missing:
        lines.extend(
            [
                "",
                "## No Data",
                "",
            ]
        )
        for item in missing:
            lines.append(
                "- `{key}` non ha ancora abbastanza richieste per essere valutato".format(
                    key=item.get("key", "-")
                )
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    with httpx.Client(base_url=args.base_url, timeout=20.0) as client:
        response = client.get(args.path)
        response.raise_for_status()
        payload = response.json()

    rendered = (
        json.dumps(payload, indent=2)
        if args.format == "json"
        else render_markdown(payload)
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    print(rendered)

    if args.fail_on_breached and payload.get("budget", {}).get("status") == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
