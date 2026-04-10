from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path
import re
from typing import Any


def _slugify(value: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    normalized = collapsed.strip("-")
    return normalized or "baseline"


def _best_passing_stage(report: dict[str, Any] | None) -> int | None:
    if not isinstance(report, dict):
        return None
    stages = report.get("stages")
    if not isinstance(stages, list):
        return None
    passing = []
    for item in stages:
        if not isinstance(item, dict) or not item.get("pass"):
            continue
        try:
            passing.append(int(item["users"]))
        except Exception:
            continue
    return max(passing) if passing else None


def summarize_performance_bundle(
    bundle: dict[str, Any],
    *,
    artifact_path: str,
    comparison_path: str | None = None,
    comparison_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_budget_payload = bundle.get("runtime_budget") if isinstance(bundle, dict) else {}
    runtime_budget = (
        runtime_budget_payload.get("budget")
        if isinstance(runtime_budget_payload, dict) and isinstance(runtime_budget_payload.get("budget"), dict)
        else {}
    )
    loadtests = bundle.get("loadtests") if isinstance(bundle, dict) else {}
    loadtests = loadtests if isinstance(loadtests, dict) else {}
    search_benchmark = bundle.get("search_benchmark") if isinstance(bundle, dict) else {}
    search_benchmark = search_benchmark if isinstance(search_benchmark, dict) else {}
    search_overall = search_benchmark.get("overall") if isinstance(search_benchmark, dict) else {}
    search_overall = search_overall if isinstance(search_overall, dict) else {}
    comparison = comparison_report if isinstance(comparison_report, dict) else {}

    return {
        "kind": bundle.get("kind", "generic"),
        "label": bundle.get("label", "baseline"),
        "generated_at": bundle.get("generated_at", ""),
        "artifact_path": artifact_path,
        "runtime_budget_status": runtime_budget.get("status", "unknown"),
        "runtime_budget_score": int(runtime_budget.get("score_percent") or 0),
        "read_heavy_best_stage": _best_passing_stage(loadtests.get("read_heavy")),
        "auth_burst_best_stage": _best_passing_stage(loadtests.get("auth_burst")),
        "mixed_crud_best_stage": _best_passing_stage(loadtests.get("mixed_crud")),
        "realtime_best_stage": _best_passing_stage(loadtests.get("realtime")),
        "search_benchmark_status": search_benchmark.get("status"),
        "search_benchmark_p95_ms": search_overall.get("p95_ms"),
        "search_benchmark_empty_ratio": search_overall.get("empty_ratio"),
        "comparison_status": comparison.get("status") if comparison else None,
        "comparison_regressions": len(comparison.get("regressions", [])) if comparison else 0,
        "comparison_path": comparison_path,
    }


def load_history_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "entries": []}
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"version": 1, "entries": []}
    entries = payload.get("entries")
    return {
        "version": int(payload.get("version") or 1),
        "entries": entries if isinstance(entries, list) else [],
    }


def save_history_manifest(path: Path, manifest: dict[str, Any]) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def add_history_entry(manifest: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    entries = list(manifest.get("entries", []))
    entries.append(entry)
    entries.sort(key=lambda item: str(item.get("generated_at", "")), reverse=True)
    return {
        "version": int(manifest.get("version") or 1),
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "entries": entries,
    }


def build_history_artifact_name(*, generated_at: str, label: str) -> str:
    timestamp = generated_at.replace(":", "").replace("-", "").replace("T", "-").replace("Z", "")
    return f"{timestamp}--{_slugify(label)}.json"


def render_performance_history_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Performance History",
        "",
        "Registro delle baseline tecniche catturate nel tempo per misurare regressioni o miglioramenti del core dev.",
        "",
        "| Kind | Label | Generated | Runtime budget | Search p95 | Read-heavy best stage | Auth burst best stage | Mixed CRUD best stage | Realtime best stage | Compare |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for entry in manifest.get("entries", []):
        if not isinstance(entry, dict):
            continue
        runtime = f"{entry.get('runtime_budget_status', 'unknown')} ({entry.get('runtime_budget_score', 0)}%)"
        search_status = entry.get("search_benchmark_status") or "-"
        search_p95 = entry.get("search_benchmark_p95_ms")
        search_value = (
            f"{search_status} / {search_p95} ms"
            if search_status != "-" and search_p95 not in (None, "")
            else search_status
        )
        compare_status = entry.get("comparison_status") or "-"
        regressions = int(entry.get("comparison_regressions") or 0)
        compare_text = compare_status if compare_status == "-" else f"{compare_status} / {regressions} regressions"
        lines.append(
            "| {kind} | {label} | {generated_at} | {runtime} | {search} | {read} | {auth} | {mixed} | {realtime} | {compare} |".format(
                kind=entry.get("kind", "-"),
                label=entry.get("label", "-"),
                generated_at=entry.get("generated_at", "-"),
                runtime=runtime,
                search=search_value,
                read=entry.get("read_heavy_best_stage") or "-",
                auth=entry.get("auth_burst_best_stage") or "-",
                mixed=entry.get("mixed_crud_best_stage") or "-",
                realtime=entry.get("realtime_best_stage") or "-",
                compare=compare_text,
            )
        )

    lines.extend(
        [
            "",
            "## Usage",
            "",
            "1. Cattura un baseline bundle con `scripts/capture_performance_baseline.py`.",
            "2. Registralo nello storico con `scripts/record_performance_history.py`.",
            "3. Confronta milestone importanti con `scripts/compare_performance_baselines.py`.",
            "",
        ]
    )
    return "\n".join(lines)
