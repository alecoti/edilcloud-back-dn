from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import platform
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = WORKSPACE_ROOT / "edilcloud-back-dn"
FRONTEND_ROOT = WORKSPACE_ROOT / "edilcloud-next"
FLUTTER_ROOT = WORKSPACE_ROOT / "edilcloud-flutter"


@dataclass(frozen=True)
class QualityCommand:
    key: str
    label: str
    command: list[str]
    cwd: Path
    skip_reason: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run quality checks and publish normalized Test Center artifacts.",
    )
    parser.add_argument(
        "--suite",
        choices=("all", "backend", "frontend-next", "flutter", "flutter-android", "flutter-ios"),
        default="all",
    )
    parser.add_argument(
        "--backend-tests",
        nargs="*",
        default=["tests/test_health.py", "tests/test_test_center_api.py"],
    )
    parser.add_argument("--output-dir", default=".tmp/test-center/quality")
    parser.add_argument("--force-ios-build", action="store_true")
    parser.add_argument("--fail-on-threshold", action="store_true")
    return parser.parse_args()


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _tail(value: str, limit: int = 4000) -> str:
    return value[-limit:]


def _run_command(item: QualityCommand) -> dict[str, Any]:
    started_at = time.time()
    if item.skip_reason:
        return {
            "key": item.key,
            "label": item.label,
            "command": _command_text(item.command),
            "cwd": str(item.cwd),
            "status": "skipped",
            "returncode": None,
            "duration_seconds": 0.0,
            "stdout_tail": "",
            "stderr_tail": item.skip_reason,
        }

    completed = subprocess.run(
        item.command,
        cwd=item.cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "key": item.key,
        "label": item.label,
        "command": _command_text(item.command),
        "cwd": str(item.cwd),
        "status": "pass" if completed.returncode == 0 else "fail",
        "returncode": completed.returncode,
        "duration_seconds": round(time.time() - started_at, 2),
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }


def _backend_commands(args: argparse.Namespace) -> list[QualityCommand]:
    return [
        QualityCommand(
            key="backend-ruff",
            label="Backend Ruff",
            command=[
                sys.executable,
                "-m",
                "ruff",
                "check",
                "src",
                "scripts",
                "tests",
            ],
            cwd=BACKEND_ROOT,
        ),
        QualityCommand(
            key="backend-pytest",
            label="Backend pytest",
            command=[
                sys.executable,
                "-m",
                "pytest",
                *args.backend_tests,
                "--basetemp=.tmp/pytest-quality",
            ],
            cwd=BACKEND_ROOT,
        ),
    ]


def _frontend_commands() -> list[QualityCommand]:
    return [
        QualityCommand(
            key="frontend-eslint",
            label="Frontend ESLint",
            command=[
                "pnpm",
                "exec",
                "eslint",
                "src/components/admin/test-center-panels.tsx",
                "src/lib/test-center/types.ts",
                "src/lib/test-center/server.ts",
            ],
            cwd=FRONTEND_ROOT,
        ),
        QualityCommand(
            key="frontend-build",
            label="Frontend build",
            command=["pnpm", "build"],
            cwd=FRONTEND_ROOT,
        ),
    ]


def _flutter_shared_commands() -> list[QualityCommand]:
    return [
        QualityCommand(
            key="flutter-analyze",
            label="Flutter analyze",
            command=["flutter", "analyze"],
            cwd=FLUTTER_ROOT,
        ),
        QualityCommand(
            key="flutter-test",
            label="Flutter test",
            command=["flutter", "test"],
            cwd=FLUTTER_ROOT,
        ),
    ]


def _flutter_target_commands(target: str, force_ios_build: bool) -> list[QualityCommand]:
    commands = _flutter_shared_commands()
    if target == "android":
        commands.append(
            QualityCommand(
                key="flutter-android-build",
                label="Flutter Android debug build",
                command=["flutter", "build", "apk", "--debug"],
                cwd=FLUTTER_ROOT,
            )
        )
        return commands

    skip_reason = ""
    if platform.system() != "Darwin" and not force_ios_build:
        skip_reason = "iOS build richiede macOS/Xcode; usare --force-ios-build su runner compatibile."
    commands.append(
        QualityCommand(
            key="flutter-ios-build",
            label="Flutter iOS debug build",
            command=["flutter", "build", "ios", "--debug", "--no-codesign"],
            cwd=FLUTTER_ROOT,
            skip_reason=skip_reason,
        )
    )
    return commands


def _selected_suites(args: argparse.Namespace) -> list[tuple[str, str | None, list[QualityCommand]]]:
    if args.suite == "backend":
        return [("backend", None, _backend_commands(args))]
    if args.suite == "frontend-next":
        return [("frontend-next", None, _frontend_commands())]
    if args.suite == "flutter-android":
        return [("flutter", "android", _flutter_target_commands("android", args.force_ios_build))]
    if args.suite == "flutter-ios":
        return [("flutter", "ios", _flutter_target_commands("ios", args.force_ios_build))]
    if args.suite == "flutter":
        return [
            ("flutter", "android", _flutter_target_commands("android", args.force_ios_build)),
            ("flutter", "ios", _flutter_target_commands("ios", args.force_ios_build)),
        ]
    return [
        ("backend", None, _backend_commands(args)),
        ("frontend-next", None, _frontend_commands()),
        ("flutter", "android", _flutter_target_commands("android", args.force_ios_build)),
        ("flutter", "ios", _flutter_target_commands("ios", args.force_ios_build)),
    ]


def _report_status(commands: list[dict[str, Any]]) -> str:
    if any(command["status"] == "fail" for command in commands):
        return "fail"
    if any(command["status"] == "skipped" for command in commands):
        return "warning"
    return "pass" if commands else "no_data"


def _focus(commands: list[dict[str, Any]]) -> list[str]:
    focus: list[str] = []
    for command in commands:
        if command["status"] == "fail":
            focus.append(f"{command['label']} fallito con exit code {command['returncode']}.")
        if command["status"] == "skipped":
            focus.append(f"{command['label']} saltato: {command['stderr_tail']}")
    return focus[:8]


def _write_report(
    *,
    output_root: Path,
    timestamp: str,
    platform_name: str,
    target: str | None,
    commands: list[dict[str, Any]],
    duration_seconds: float,
) -> dict[str, Any]:
    slug = platform_name if target is None else f"{platform_name}-{target}"
    report_dir = output_root / f"{timestamp}--{slug}"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "quality-report.json"
    status = _report_status(commands)
    report = {
        "engine": "quality-suite",
        "status": status,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform_name,
        "target": target,
        "suite": "quality",
        "summary": {
            "commands": len(commands),
            "passed": sum(command["status"] == "pass" for command in commands),
            "failed": sum(command["status"] == "fail" for command in commands),
            "skipped": sum(command["status"] == "skipped" for command in commands),
            "duration_seconds": round(duration_seconds, 2),
        },
        "commands": commands,
        "focus": _focus(commands),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    args = parse_args()
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    output_root = (BACKEND_ROOT / args.output_dir).resolve()
    reports: list[dict[str, Any]] = []

    for platform_name, target, command_plan in _selected_suites(args):
        started_at = time.time()
        commands = [_run_command(item) for item in command_plan]
        reports.append(
            _write_report(
                output_root=output_root,
                timestamp=timestamp,
                platform_name=platform_name,
                target=target,
                commands=commands,
                duration_seconds=time.time() - started_at,
            )
        )

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reports": reports,
        "status": "fail" if any(report["status"] == "fail" for report in reports) else "pass",
    }
    print(json.dumps(summary, indent=2))

    if args.fail_on_threshold and summary["status"] == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
