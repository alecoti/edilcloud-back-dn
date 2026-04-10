import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.assistant.answer_planner import plan_assistant_answer
from edilcloud.modules.assistant.models import AssistantResponseMode
from edilcloud.modules.assistant.query_router import classify_assistant_query


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[2] / "data" / "assistant_eval_dataset.json"


class Command(BaseCommand):
    help = "Esegue una eval rapida del router/planner assistant su un dataset versionato."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset",
            type=str,
            default=str(DEFAULT_DATASET_PATH),
            help="Path del dataset JSON da valutare.",
        )

    def handle(self, *args, **options):
        dataset_path = Path(options["dataset"]).resolve()
        if not dataset_path.exists():
            raise CommandError(f"Dataset non trovato: {dataset_path}")

        rows = json.loads(dataset_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise CommandError("Il dataset assistant deve essere una lista JSON.")

        results = []
        passed = 0
        for row in rows:
            question = str(row.get("question") or "").strip()
            if not question:
                continue
            route = classify_assistant_query(question)
            plan = plan_assistant_answer(
                question=question,
                route=route,
                response_mode=AssistantResponseMode.AUTO,
            )
            expected_intent = row.get("expected_intent")
            expected_strategy = row.get("expected_strategy")
            expected_target_length = row.get("expected_target_length")

            checks = {
                "intent": route.intent == expected_intent if expected_intent else True,
                "strategy": route.strategy == expected_strategy if expected_strategy else True,
                "target_length": plan.target_length == expected_target_length if expected_target_length else True,
            }
            ok = all(checks.values())
            if ok:
                passed += 1
            results.append(
                {
                    "question": question,
                    "route": {"intent": route.intent, "strategy": route.strategy},
                    "plan": {"target_length": plan.target_length, "answer_mode": plan.answer_mode},
                    "checks": checks,
                    "ok": ok,
                }
            )

        report = {
            "dataset": str(dataset_path),
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_rate": round((passed / max(1, len(results))) * 100, 2),
            "results": results,
        }
        self.stdout.write(json.dumps(report, ensure_ascii=True, indent=2))
