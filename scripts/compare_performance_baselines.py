from __future__ import annotations

import argparse
import json
from pathlib import Path

from edilcloud.platform.performance_baseline import (
    ComparisonThresholds,
    compare_performance_baselines,
    render_baseline_comparison_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two performance baseline bundles and fail on regression when requested.",
    )
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--max-p95-regression-ratio", type=float, default=0.15)
    parser.add_argument("--max-failure-ratio-increase", type=float, default=0.005)
    parser.add_argument("--max-delivery-ratio-drop", type=float, default=0.01)
    parser.add_argument("--output", default="")
    parser.add_argument("--fail-on-regression", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline_path = Path(args.baseline).resolve()
    current_path = Path(args.current).resolve()
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = json.loads(current_path.read_text(encoding="utf-8"))
    report = compare_performance_baselines(
        baseline,
        current,
        thresholds=ComparisonThresholds(
            max_p95_regression_ratio=args.max_p95_regression_ratio,
            max_failure_ratio_increase=args.max_failure_ratio_increase,
            max_delivery_ratio_drop=args.max_delivery_ratio_drop,
        ),
    )

    rendered = (
        json.dumps(report, indent=2)
        if args.format == "json"
        else render_baseline_comparison_markdown(report)
    )

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered, encoding="utf-8")

    print(rendered)
    if args.fail_on_regression and report.get("status") == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
