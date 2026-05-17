import json
from pathlib import Path
import subprocess
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "record_action_run.py"


def test_record_action_run_writes_ledger_artifact(tmp_path):
    stdout_file = tmp_path / "stdout.log"
    stderr_file = tmp_path / "stderr.log"
    stdout_file.write_text("ok\n" + ("x" * 4100), encoding="utf-8")
    stderr_file.write_text("Type error", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--action-id",
            "action-frontend-1",
            "--issue-id",
            "issue-frontend-1",
            "--operation",
            "rerun_quality_suite",
            "--platform",
            "frontend-next",
            "--category",
            "quality",
            "--command",
            "pnpm build",
            "--cwd",
            "edilcloud-next",
            "--returncode",
            "1",
            "--summary",
            "TypeScript build failed.",
            "--stdout-file",
            str(stdout_file),
            "--stderr-file",
            str(stderr_file),
            "--evidence",
            "Build non conclusa.",
            "--next-step",
            "Correggere il tipo e ripetere il dry-run.",
            "--actor-id",
            "ops@example.com",
            "--actor-label",
            "Ops",
            "--artifact",
            "html=report.html",
            "--duration-seconds",
            "8.45",
            "--generated-at",
            "2026-05-17T10:00:00Z",
            "--run-name",
            "frontend-build-fail",
            "--output-dir",
            str(tmp_path / "action-runs"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    artifact_path = Path(summary["artifact_path"])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["status"] == "fail"
    assert payload["mode"] == "dry_run"
    assert payload["action_id"] == "action-frontend-1"
    assert payload["issue_id"] == "issue-frontend-1"
    assert payload["operation"] == "rerun_quality_suite"
    assert payload["returncode"] == 1
    assert payload["duration_seconds"] == 8.45
    assert payload["stdout_tail"] == "x" * 4000
    assert payload["stderr_tail"] == "Type error"
    assert payload["actor"]["label"] == "Ops"
    assert payload["artifacts"] == {"html": "report.html"}
    assert payload["audit"] == {
        "will_modify_code": False,
        "will_touch_production": False,
        "approval_required": True,
        "approved_by": None,
    }


def test_record_action_run_rejects_apply_without_approval(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--action-id",
            "action-frontend-1",
            "--operation",
            "rerun_quality_suite",
            "--platform",
            "frontend-next",
            "--category",
            "quality",
            "--mode",
            "apply",
            "--output-dir",
            str(tmp_path / "action-runs"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--mode apply richiede --approved-by" in result.stderr
    assert not (tmp_path / "action-runs").exists()
