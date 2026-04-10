from __future__ import annotations

import argparse
import json
from pathlib import Path

from edilcloud.platform.performance_baseline import compare_performance_baselines
from edilcloud.platform.performance_history import (
    add_history_entry,
    build_history_artifact_name,
    load_history_manifest,
    render_performance_history_markdown,
    save_history_manifest,
    summarize_performance_bundle,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Register a captured performance baseline into the repo history and regenerate the dashboard.",
    )
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--history-dir", default="docs/performance-history")
    parser.add_argument("--dashboard", default="docs/PERFORMANCE_HISTORY.md")
    parser.add_argument("--compare-to-latest", action="store_true")
    return parser.parse_args()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = parse_args()
    bundle_path = Path(args.bundle).resolve()
    history_dir = Path(args.history_dir).resolve()
    dashboard_path = Path(args.dashboard).resolve()
    manifest_path = history_dir / "index.json"
    artifacts_dir = history_dir / "bundles"
    comparisons_dir = history_dir / "comparisons"

    bundle = _read_json(bundle_path)
    label = str(bundle.get("label") or "baseline")
    generated_at = str(bundle.get("generated_at") or "unknown")

    artifact_name = build_history_artifact_name(generated_at=generated_at, label=label)
    artifact_path = artifacts_dir / artifact_name
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    manifest = load_history_manifest(manifest_path)
    comparison_path_value: str | None = None
    comparison_report: dict | None = None

    if args.compare_to_latest and manifest.get("entries"):
        latest_entry = manifest["entries"][0]
        latest_artifact = latest_entry.get("artifact_path")
        if latest_artifact:
            previous_bundle = _read_json(Path(str(latest_artifact)).resolve())
            comparison_report = compare_performance_baselines(previous_bundle, bundle)
            comparison_name = artifact_name.replace(".json", "--comparison.json")
            comparison_path = comparisons_dir / comparison_name
            comparison_path.parent.mkdir(parents=True, exist_ok=True)
            comparison_path.write_text(json.dumps(comparison_report, indent=2), encoding="utf-8")
            comparison_path_value = str(comparison_path)

    entry = summarize_performance_bundle(
        bundle,
        artifact_path=str(artifact_path),
        comparison_path=comparison_path_value,
        comparison_report=comparison_report,
    )
    manifest = add_history_entry(manifest, entry)
    save_history_manifest(manifest_path, manifest)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    dashboard_path.write_text(render_performance_history_markdown(manifest), encoding="utf-8")

    print(
        json.dumps(
            {
                "artifact_path": str(artifact_path),
                "manifest_path": str(manifest_path),
                "dashboard_path": str(dashboard_path),
                "comparison_path": comparison_path_value,
                "label": label,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
