from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = WORKSPACE_ROOT / "edilcloud-back-dn"
FRONTEND_ROOT = WORKSPACE_ROOT / "edilcloud-next"
SCRIPT_DIR = Path(__file__).resolve().parent
SUPPORTED_OPERATIONS = {"rerun_quality_suite", "rerun_loadtest_suite"}
LOADTEST_PROFILES = {"auth-burst", "mixed-crud", "read-heavy"}

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from record_action_run import build_payload, write_payload  # noqa: E402


class ControlledExecutorError(RuntimeError):
    pass


@dataclass(frozen=True)
class OperationPlan:
    command: list[str]
    cwd: Path
    operation: str
    summary: str


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _quality_suite_for_action(action: dict[str, Any]) -> str:
    platform = str(action.get("platform") or "")
    target = action.get("target")
    if platform == "backend":
        return "backend"
    if platform == "frontend-next":
        return "frontend-next"
    if platform == "flutter" and target == "android":
        return "flutter-android"
    if platform == "flutter" and target == "ios":
        return "flutter-ios"
    if platform == "flutter":
        return "flutter"
    raise ControlledExecutorError(f"Piattaforma quality non supportata: {platform}.")


def _build_quality_plan(action: dict[str, Any], args: argparse.Namespace) -> OperationPlan:
    suite = _quality_suite_for_action(action)
    command = [
        sys.executable,
        "scripts/run_quality_suite.py",
        "--suite",
        suite,
        "--output-dir",
        args.quality_output_dir,
        "--fail-on-threshold",
    ]
    return OperationPlan(
        command=command,
        cwd=BACKEND_ROOT,
        operation="rerun_quality_suite",
        summary=f"Rilancio quality suite {suite}.",
    )


def _build_loadtest_plan(action: dict[str, Any], args: argparse.Namespace) -> OperationPlan:
    profile = args.loadtest_profile or "read-heavy"
    if profile not in LOADTEST_PROFILES:
        raise ControlledExecutorError(f"Profilo Locust non supportato: {profile}.")
    command = [
        sys.executable,
        "scripts/run_locust_suite.py",
        "--profile",
        profile,
        "--host",
        args.loadtest_host,
        "--users",
        str(args.loadtest_users),
        "--spawn-rate",
        str(args.loadtest_spawn_rate),
        "--run-time",
        args.loadtest_run_time,
        "--output-dir",
        args.loadtest_output_dir,
        "--fail-on-threshold",
    ]
    return OperationPlan(
        command=command,
        cwd=BACKEND_ROOT,
        operation="rerun_loadtest_suite",
        summary=f"Rilancio Locust {profile}.",
    )


def build_operation_plan(action: dict[str, Any], args: argparse.Namespace) -> OperationPlan:
    if args.operation == "rerun_quality_suite":
        return _build_quality_plan(action, args)
    if args.operation == "rerun_loadtest_suite":
        return _build_loadtest_plan(action, args)
    raise ControlledExecutorError(f"Operazione non supportata: {args.operation}.")


def _setup_django() -> None:
    src_path = BACKEND_ROOT / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edilcloud.settings.local")
    import django

    django.setup()


def load_action(action_id: str) -> dict[str, Any]:
    _setup_django()
    from edilcloud.platform.test_center_actions import build_test_center_action_detail

    action = build_test_center_action_detail(action_id)
    if action is None:
        raise ControlledExecutorError(f"Azione Test Center non trovata: {action_id}.")
    return action


def validate_action(action: dict[str, Any], args: argparse.Namespace) -> None:
    if args.operation not in SUPPORTED_OPERATIONS:
        raise ControlledExecutorError(f"Operazione non supportata: {args.operation}.")
    allowed_operations = set(action.get("allowed_operations") or [])
    if args.operation not in allowed_operations:
        raise ControlledExecutorError(
            f"Operazione {args.operation} non consentita per action {args.action_id}."
        )
    if action.get("state") == "blocked":
        raise ControlledExecutorError(f"Action {args.action_id} bloccata.")
    audit = action.get("audit") if isinstance(action.get("audit"), dict) else {}
    requires_approval = bool(audit.get("requires_operator_approval"))
    if (requires_approval or action.get("state") == "needs_human_review") and not args.approved_by:
        raise ControlledExecutorError(
            f"Action {args.action_id} richiede --approved-by prima del dry-run."
        )


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _record_namespace(
    *,
    args: argparse.Namespace,
    action: dict[str, Any],
    plan: OperationPlan,
    returncode: int | None,
    status: str,
    started_at: str | None,
    finished_at: str | None,
    duration_seconds: float,
    stdout: str,
    stderr: str,
) -> argparse.Namespace:
    source_issue = action.get("source_issue") if isinstance(action.get("source_issue"), dict) else {}
    audit = action.get("audit") if isinstance(action.get("audit"), dict) else {}
    return argparse.Namespace(
        action_id=args.action_id,
        issue_id=str(action.get("issue_id") or source_issue.get("id") or ""),
        operation=plan.operation,
        platform=str(action.get("platform") or "unknown"),
        target=action.get("target"),
        category=str(action.get("category") or "unknown"),
        status=status,
        mode="dry_run",
        command=_command_text(plan.command),
        cwd=str(plan.cwd),
        returncode=returncode,
        summary=plan.summary if status != "fail" else f"{plan.summary} Fallito.",
        stdout=stdout,
        stderr=stderr,
        stdout_file=None,
        stderr_file=None,
        generated_at=_utc_now(),
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        actor_kind=args.actor_kind,
        actor_id=args.actor_id,
        actor_label=args.actor_label,
        evidence=[
            f"Action state: {action.get('state')}",
            f"Risk: {action.get('risk')}",
        ],
        next_step=(
            "Leggere stderr/stdout e aggiornare la issue prima di un nuovo tentativo."
            if status == "fail"
            else "Verificare la dashboard Test Center e chiudere la issue se non ricompare."
        ),
        artifacts={},
        will_modify_code=False,
        will_touch_production=False,
        approval_required=bool(audit.get("requires_operator_approval", True)),
        approved_by=args.approved_by,
        output_dir=args.output_dir,
        run_name=args.run_name,
    )


def execute_action(action: dict[str, Any], args: argparse.Namespace) -> tuple[int, Path]:
    validate_action(action, args)
    plan = build_operation_plan(action, args)
    started_at = _utc_now()
    started = time.time()

    if args.plan_only:
        record_args = _record_namespace(
            args=args,
            action=action,
            plan=plan,
            returncode=None,
            status="planned",
            started_at=None,
            finished_at=None,
            duration_seconds=0.0,
            stdout="",
            stderr="",
        )
        payload = build_payload(record_args)
        return 0, write_payload(record_args, payload)

    completed = subprocess.run(
        plan.command,
        cwd=plan.cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    finished_at = _utc_now()
    duration_seconds = time.time() - started
    status = "pass" if completed.returncode == 0 else "fail"
    record_args = _record_namespace(
        args=args,
        action=action,
        plan=plan,
        returncode=completed.returncode,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=duration_seconds,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    payload = build_payload(record_args)
    artifact_path = write_payload(record_args, payload)
    return completed.returncode, artifact_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Execute a whitelisted Test Center action operation and record the attempt. "
            "This wrapper only supports controlled dry-run operations."
        )
    )
    parser.add_argument("--action-id", required=True)
    parser.add_argument("--operation", choices=sorted(SUPPORTED_OPERATIONS), required=True)
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--actor-kind", default="operator")
    parser.add_argument("--actor-id", default="local")
    parser.add_argument("--actor-label", default="")
    parser.add_argument("--output-dir", default=".tmp/test-center/action-runs")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--quality-output-dir", default=".tmp/test-center/quality")
    parser.add_argument("--loadtest-output-dir", default=".tmp/test-center/loadtests")
    parser.add_argument("--loadtest-profile", choices=sorted(LOADTEST_PROFILES), default=None)
    parser.add_argument("--loadtest-host", default="http://localhost:3000")
    parser.add_argument("--loadtest-users", type=int, default=10)
    parser.add_argument("--loadtest-spawn-rate", type=float, default=5.0)
    parser.add_argument("--loadtest-run-time", default="2m")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        action = load_action(args.action_id)
        returncode, artifact_path = execute_action(action, args)
    except ControlledExecutorError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "artifact_path": str(artifact_path),
                "returncode": returncode,
                "action_id": args.action_id,
                "operation": args.operation,
            },
            indent=2,
        )
    )
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
