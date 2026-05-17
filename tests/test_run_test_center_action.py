import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "run_test_center_action.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("run_test_center_action_test", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def frontend_action() -> dict:
    return {
        "id": "action-frontend-1",
        "issue_id": "issue-frontend-1",
        "state": "ready_for_dry_run",
        "risk": "low",
        "platform": "frontend-next",
        "target": None,
        "category": "quality",
        "allowed_operations": ["rerun_quality_suite"],
        "audit": {"requires_operator_approval": False},
        "source_issue": {"id": "issue-frontend-1"},
    }


def test_run_test_center_action_executes_allowed_quality_operation(monkeypatch, tmp_path):
    module = load_script_module()
    captured: dict = {}

    def fake_run(command, *, cwd, capture_output, text, check):
        captured["command"] = command
        captured["cwd"] = cwd
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["check"] = check
        return SimpleNamespace(returncode=0, stdout="quality ok", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    args = module.parse_args(
        [
            "--action-id",
            "action-frontend-1",
            "--operation",
            "rerun_quality_suite",
            "--output-dir",
            str(tmp_path / "action-runs"),
            "--run-name",
            "frontend-quality-pass",
        ]
    )

    returncode, artifact_path = module.execute_action(frontend_action(), args)

    assert returncode == 0
    assert captured["cwd"] == module.BACKEND_ROOT
    assert "scripts/run_quality_suite.py" in captured["command"]
    assert "--suite" in captured["command"]
    assert "frontend-next" in captured["command"]
    assert "--fail-on-threshold" in captured["command"]

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["mode"] == "dry_run"
    assert payload["action_id"] == "action-frontend-1"
    assert payload["issue_id"] == "issue-frontend-1"
    assert payload["operation"] == "rerun_quality_suite"
    assert payload["platform"] == "frontend-next"
    assert payload["returncode"] == 0
    assert payload["stdout_tail"] == "quality ok"
    assert payload["audit"]["will_modify_code"] is False
    assert payload["audit"]["will_touch_production"] is False


def test_run_test_center_action_requires_approval_for_manual_review(tmp_path):
    module = load_script_module()
    action = frontend_action()
    action["state"] = "needs_human_review"
    action["audit"] = {"requires_operator_approval": True}
    args = module.parse_args(
        [
            "--action-id",
            "action-frontend-1",
            "--operation",
            "rerun_quality_suite",
            "--output-dir",
            str(tmp_path / "action-runs"),
        ]
    )

    with pytest.raises(module.ControlledExecutorError, match="richiede --approved-by"):
        module.execute_action(action, args)


def test_run_test_center_action_plan_only_records_without_subprocess(monkeypatch, tmp_path):
    module = load_script_module()

    def fail_run(*args, **kwargs):
        raise AssertionError("subprocess.run non dovrebbe essere chiamato")

    monkeypatch.setattr(module.subprocess, "run", fail_run)
    args = module.parse_args(
        [
            "--action-id",
            "action-frontend-1",
            "--operation",
            "rerun_quality_suite",
            "--plan-only",
            "--output-dir",
            str(tmp_path / "action-runs"),
            "--run-name",
            "frontend-quality-planned",
        ]
    )

    returncode, artifact_path = module.execute_action(frontend_action(), args)

    assert returncode == 0
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert payload["status"] == "planned"
    assert payload["returncode"] is None
    assert payload["command"]
