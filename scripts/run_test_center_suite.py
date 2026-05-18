from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from record_action_run import build_payload, write_payload  # noqa: E402


def _setup_django() -> None:
    src_path = BACKEND_ROOT / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "edilcloud.settings.local")
    import django

    django.setup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Test Center catalog suite.")
    parser.add_argument("--suite-id", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--actor-id", default="local")
    parser.add_argument("--actor-label", default="")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--loadtest-host", default="http://localhost:3000")
    parser.add_argument("--loadtest-users", type=int, default=10)
    parser.add_argument("--loadtest-spawn-rate", type=float, default=5.0)
    parser.add_argument("--loadtest-run-time", default="2m")
    parser.add_argument("--output-dir", default=".tmp/test-center/action-runs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _setup_django()
    from edilcloud.platform.test_center_catalog import get_catalog_suite, _local_command

    suite = get_catalog_suite(args.suite_id)
    if suite is None:
        print(f"Suite catalogo non trovata: {args.suite_id}", file=sys.stderr)
        return 2
    command = _local_command(
        suite,
        loadtest_host=args.loadtest_host,
        loadtest_users=args.loadtest_users,
        loadtest_spawn_rate=args.loadtest_spawn_rate,
        loadtest_run_time=args.loadtest_run_time,
    )
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = time.time()
    completed = subprocess.run(
        command,
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record_args = argparse.Namespace(
        action_id=f"catalog:{suite['id']}",
        issue_id="",
        operation=suite["operation"],
        platform=suite["platform"],
        target=suite["target"],
        category=suite["category"],
        status="pass" if completed.returncode == 0 else "fail",
        mode="dry_run",
        command=" ".join(command),
        cwd=str(BACKEND_ROOT),
        returncode=completed.returncode,
        summary=f"Catalogo {suite['label']}.",
        stdout=completed.stdout,
        stderr=completed.stderr,
        stdout_file=None,
        stderr_file=None,
        generated_at=started_at,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=time.time() - started,
        actor_kind="superuser",
        actor_id=args.actor_id,
        actor_label=args.actor_label,
        evidence=[f"Catalog suite: {suite['id']}", f"Runner: {suite['runner']}"],
        next_step=(
            "Verificare il report prodotto e confrontarlo con la soglia attesa."
            if completed.returncode == 0
            else "Aprire stdout/stderr e correggere la prima causa bloccante."
        ),
        artifacts={},
        will_modify_code=False,
        will_touch_production=False,
        approval_required=suite["risk"] != "low",
        approved_by=args.approved_by or None,
        output_dir=args.output_dir,
        run_name=args.run_name,
    )
    payload = build_payload(record_args)
    artifact_path = write_payload(record_args, payload)
    print(json.dumps({"artifact_path": str(artifact_path), "returncode": completed.returncode}))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
