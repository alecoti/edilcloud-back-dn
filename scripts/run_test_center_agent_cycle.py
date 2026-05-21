from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _setup_django(settings_module: str) -> None:
    src_path = BACKEND_ROOT / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    import django

    django.setup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan one guarded Test Center agent cycle without applying changes."
    )
    parser.add_argument("--max-total", type=int, default=3)
    parser.add_argument("--max-per-platform", type=int, default=1)
    parser.add_argument("--max-per-category", type=int, default=2)
    parser.add_argument("--cooldown-hours", type=float, default=1.0)
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--settings", default="edilcloud.settings.local")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _setup_django(args.settings)
    from edilcloud.platform.test_center_agent_cycle import (
        build_test_center_agent_cycle_plan,
        record_agent_cycle_plan,
    )

    plan = build_test_center_agent_cycle_plan(
        max_total=args.max_total,
        max_per_platform=args.max_per_platform,
        max_per_category=args.max_per_category,
        cooldown_hours=args.cooldown_hours,
    )
    artifact_path = record_agent_cycle_plan(plan) if args.record else None
    print(
        json.dumps(
            {
                "artifact_path": str(artifact_path) if artifact_path else None,
                "plan": plan,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
