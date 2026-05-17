from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = WORKSPACE_ROOT / "edilcloud-back-dn"
VALID_STATUSES = {"planned", "running", "pass", "fail", "blocked", "cancelled", "skipped"}
VALID_MODES = {"dry_run", "apply"}
TAIL_LIMIT = 4000


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip())
    return cleaned.strip("-")[:80] or "run"


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())


def _tail(value: str) -> str:
    return value[-TAIL_LIMIT:]


def _read_text_arg(value: str, file_path: str | None) -> str:
    if file_path:
        return Path(file_path).resolve().read_text(encoding="utf-8")
    return value


def _key_value_pairs(items: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Valore non valido '{item}'. Usa formato chiave=valore.")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Valore non valido '{item}'. La chiave non puo essere vuota.")
        pairs[key] = value.strip()
    return pairs


def _status_from_args(args: argparse.Namespace) -> str:
    if args.status:
        return args.status
    if args.returncode is None:
        return "planned"
    return "pass" if args.returncode == 0 else "fail"


def _output_root(path_value: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path.resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Record an already executed Test Center action attempt as a run ledger artifact. "
            "This script does not execute remediation commands."
        )
    )
    parser.add_argument("--action-id", required=True)
    parser.add_argument("--issue-id", default="")
    parser.add_argument("--operation", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--target", default=None)
    parser.add_argument("--category", required=True)
    parser.add_argument("--status", choices=sorted(VALID_STATUSES), default=None)
    parser.add_argument("--mode", choices=sorted(VALID_MODES), default="dry_run")
    parser.add_argument("--command", default="")
    parser.add_argument("--cwd", default="")
    parser.add_argument("--returncode", type=int, default=None)
    parser.add_argument("--summary", default="")
    parser.add_argument("--stdout", default="")
    parser.add_argument("--stderr", default="")
    parser.add_argument("--stdout-file", default=None)
    parser.add_argument("--stderr-file", default=None)
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--started-at", default=None)
    parser.add_argument("--finished-at", default=None)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--actor-kind", default="operator")
    parser.add_argument("--actor-id", default="local")
    parser.add_argument("--actor-label", default="")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--next-step", default="")
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--will-modify-code", action="store_true")
    parser.add_argument("--will-touch-production", action="store_true")
    parser.add_argument("--approval-required", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--approved-by", default=None)
    parser.add_argument("--output-dir", default=".tmp/test-center/action-runs")
    parser.add_argument("--run-name", default=None)
    args = parser.parse_args()

    if args.mode == "apply" and args.approval_required and not args.approved_by:
        parser.error("--mode apply richiede --approved-by oppure --no-approval-required.")
    if args.will_touch_production and not args.approved_by:
        parser.error("--will-touch-production richiede --approved-by.")
    try:
        args.artifacts = _key_value_pairs(args.artifact)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    stdout_tail = _tail(_read_text_arg(args.stdout, args.stdout_file))
    stderr_tail = _tail(_read_text_arg(args.stderr, args.stderr_file))
    actor_label = args.actor_label or args.actor_id or "local"
    return {
        "status": _status_from_args(args),
        "mode": args.mode,
        "action_id": args.action_id,
        "issue_id": args.issue_id or None,
        "operation": args.operation,
        "platform": args.platform,
        "target": args.target,
        "category": args.category,
        "generated_at": args.generated_at or _utc_now(),
        "started_at": args.started_at,
        "finished_at": args.finished_at,
        "duration_seconds": round(max(args.duration_seconds, 0.0), 2),
        "actor": {
            "kind": args.actor_kind,
            "id": args.actor_id,
            "label": actor_label,
        },
        "command": args.command,
        "cwd": args.cwd,
        "returncode": args.returncode,
        "summary": args.summary,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "artifacts": args.artifacts,
        "evidence": list(args.evidence),
        "next_step": args.next_step,
        "audit": {
            "will_modify_code": bool(args.will_modify_code),
            "will_touch_production": bool(args.will_touch_production),
            "approval_required": bool(args.approval_required),
            "approved_by": args.approved_by,
        },
    }


def write_payload(args: argparse.Namespace, payload: dict[str, Any]) -> Path:
    output_root = _output_root(args.output_dir)
    run_name = args.run_name
    if not run_name:
        run_name = f"{_timestamp()}--{_slug(args.action_id)}--{_slug(args.operation)}"
    run_dir = output_root / _slug(run_name)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = run_dir / "action-run.json"
    artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return artifact_path


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    artifact_path = write_payload(args, payload)
    print(
        json.dumps(
            {
                "artifact_path": str(artifact_path),
                "status": payload["status"],
                "action_id": payload["action_id"],
                "operation": payload["operation"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
