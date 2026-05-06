import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from edilcloud.modules.assistant.answer_planner import plan_assistant_answer
from edilcloud.modules.assistant.models import AssistantResponseMode
from edilcloud.modules.assistant.quality_reporting import (
    build_quality_report,
    load_project_assistant_run_logs,
)
from edilcloud.modules.assistant.query_router import classify_assistant_query


DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[2] / "data" / "assistant_eval_dataset.json"


class Command(BaseCommand):
    help = "Applica un gate di qualita assistant su eval dataset e run log persistiti."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset",
            type=str,
            default=str(DEFAULT_DATASET_PATH),
            help="Path del dataset JSON da valutare.",
        )
        parser.add_argument("--limit", type=int, default=200, help="Numero massimo di run assistant da analizzare.")
        parser.add_argument("--project-id", type=int, help="Filtra i run log per progetto.")
        parser.add_argument("--min-pass-rate", type=float, default=100.0, help="Soglia minima pass rate dataset.")
        parser.add_argument(
            "--min-supported-rate",
            type=float,
            default=95.0,
            help="Soglia minima supported_rate media sui run log.",
        )
        parser.add_argument(
            "--min-topical-rate",
            type=float,
            default=90.0,
            help="Soglia minima topical_rate media sui run log.",
        )
        parser.add_argument(
            "--min-grounding",
            type=float,
            default=0.1,
            help="Soglia minima avg_grounding media sui run log.",
        )
        parser.add_argument(
            "--max-mismatch",
            type=float,
            default=0.25,
            help="Soglia massima avg_mismatch media sui run log.",
        )
        parser.add_argument(
            "--min-citation-support",
            type=float,
            default=0.05,
            help="Soglia minima media citation_support sui run log con metriche nuove.",
        )
        parser.add_argument(
            "--max-noisy-context",
            type=float,
            default=0.75,
            help="Soglia massima media noisy_context sui run log con metriche nuove.",
        )
        parser.add_argument(
            "--max-weak-evidence-rate",
            type=float,
            default=50.0,
            help="Soglia massima percentuale weak_evidence sui run log con metriche nuove.",
        )
        parser.add_argument(
            "--min-recall-at-5",
            type=float,
            default=0.2,
            help="Soglia minima media recall@5 sui run log con metriche ranking retrieval.",
        )
        parser.add_argument(
            "--min-ndcg-at-5",
            type=float,
            default=0.45,
            help="Soglia minima media nDCG@5 sui run log con metriche ranking retrieval.",
        )
        parser.add_argument(
            "--max-weak-ranking-rate",
            type=float,
            default=50.0,
            help="Soglia massima percentuale weak_retrieval_ranking sui run log con metriche ranking.",
        )

    def handle(self, *args, **options):
        dataset_report = evaluate_dataset(Path(options["dataset"]).resolve())
        close_old_connections()
        run_logs, error = load_project_assistant_run_logs(
            limit=max(int(options.get("limit") or 200), 1),
            project_id=options.get("project_id"),
        )
        if error:
            raise CommandError(json.dumps(error, ensure_ascii=True))

        run_log_report = build_quality_report(run_logs or [])
        gate = evaluate_gate(
            dataset_report=dataset_report,
            run_log_report=run_log_report,
            min_pass_rate=float(options["min_pass_rate"]),
            min_supported_rate=float(options["min_supported_rate"]),
            min_topical_rate=float(options["min_topical_rate"]),
            min_grounding=float(options["min_grounding"]),
            max_mismatch=float(options["max_mismatch"]),
            min_citation_support=float(options["min_citation_support"]),
            max_noisy_context=float(options["max_noisy_context"]),
            max_weak_evidence_rate=float(options["max_weak_evidence_rate"]),
            min_recall_at_5=float(options["min_recall_at_5"]),
            min_ndcg_at_5=float(options["min_ndcg_at_5"]),
            max_weak_ranking_rate=float(options["max_weak_ranking_rate"]),
        )

        payload = {
            "dataset": dataset_report,
            "run_logs": run_log_report,
            "gate": gate,
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=True, indent=2))
        if not gate["ok"]:
            raise CommandError("Assistant quality gate failed.")


def evaluate_dataset(dataset_path: Path) -> dict:
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
        expected_source_types = [
            str(source_type)
            for source_type in list(row.get("expected_source_types") or [])
            if str(source_type).strip()
        ]
        checks = {
            "intent": route.intent == row.get("expected_intent") if row.get("expected_intent") else True,
            "strategy": route.strategy == row.get("expected_strategy") if row.get("expected_strategy") else True,
            "target_length": (
                plan.target_length == row.get("expected_target_length")
                if row.get("expected_target_length")
                else True
            ),
            "answer_shape": (
                plan.response_structure == row.get("expected_answer_shape")
                if row.get("expected_answer_shape")
                else True
            ),
            "source_types": (
                set(expected_source_types).issubset(set(route.selected_source_types))
                if expected_source_types
                else True
            ),
        }
        ok = all(checks.values())
        if ok:
            passed += 1
        results.append({"question": question, "checks": checks, "ok": ok})

    total = len(results)
    return {
        "dataset": str(dataset_path),
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": round((passed / max(1, total)) * 100, 2),
    }


def evaluate_gate(
    *,
    dataset_report: dict,
    run_log_report: dict,
    min_pass_rate: float,
    min_supported_rate: float,
    min_topical_rate: float,
    min_grounding: float,
    max_mismatch: float,
    min_citation_support: float,
    max_noisy_context: float,
    max_weak_evidence_rate: float,
    min_recall_at_5: float,
    min_ndcg_at_5: float,
    max_weak_ranking_rate: float,
) -> dict:
    per_intent = run_log_report.get("success_rate_per_intent") or {}
    supported_rates = [float(item.get("supported_rate") or 0.0) for item in per_intent.values()]
    topical_rates = [float(item.get("topical_rate") or 0.0) for item in per_intent.values()]
    grounding_values = [float(item.get("avg_grounding") or 0.0) for item in per_intent.values()]
    mismatch_values = [float(item.get("avg_mismatch") or 0.0) for item in per_intent.values()]
    quality_items = [
        item
        for item in per_intent.values()
        if int(item.get("context_quality_count") or 0) > 0
    ]
    citation_support_values = [float(item.get("avg_citation_support") or 0.0) for item in quality_items]
    noisy_context_values = [float(item.get("avg_noisy_context") or 0.0) for item in quality_items]
    weak_evidence_rates = [float(item.get("weak_evidence_rate") or 0.0) for item in quality_items]
    ranking_items = [
        item
        for item in per_intent.values()
        if int(item.get("ranking_quality_count") or 0) > 0
    ]
    recall_at_5_values = [float(item.get("avg_recall_at_5") or 0.0) for item in ranking_items]
    ndcg_at_5_values = [float(item.get("avg_ndcg_at_5") or 0.0) for item in ranking_items]
    weak_ranking_rates = [float(item.get("weak_ranking_rate") or 0.0) for item in ranking_items]

    avg_supported_rate = round(sum(supported_rates) / max(1, len(supported_rates)), 2)
    avg_topical_rate = round(sum(topical_rates) / max(1, len(topical_rates)), 2)
    avg_grounding = round(sum(grounding_values) / max(1, len(grounding_values)), 3)
    avg_mismatch = round(sum(mismatch_values) / max(1, len(mismatch_values)), 3)
    avg_citation_support = round(sum(citation_support_values) / max(1, len(citation_support_values)), 3)
    avg_noisy_context = round(sum(noisy_context_values) / max(1, len(noisy_context_values)), 3)
    avg_weak_evidence_rate = round(sum(weak_evidence_rates) / max(1, len(weak_evidence_rates)), 2)
    avg_recall_at_5 = round(sum(recall_at_5_values) / max(1, len(recall_at_5_values)), 3)
    avg_ndcg_at_5 = round(sum(ndcg_at_5_values) / max(1, len(ndcg_at_5_values)), 3)
    avg_weak_ranking_rate = round(sum(weak_ranking_rates) / max(1, len(weak_ranking_rates)), 2)
    has_context_quality_metrics = bool(quality_items)
    has_ranking_quality_metrics = bool(ranking_items)
    has_run_log_metrics = bool(per_intent)

    checks = {
        "dataset_pass_rate": float(dataset_report.get("pass_rate") or 0.0) >= min_pass_rate,
    }
    if has_run_log_metrics:
        checks.update(
            {
                "supported_rate": avg_supported_rate >= min_supported_rate,
                "topical_rate": avg_topical_rate >= min_topical_rate,
                "grounding": avg_grounding >= min_grounding,
                "mismatch": avg_mismatch <= max_mismatch,
            }
        )
    if has_context_quality_metrics:
        checks.update(
            {
                "citation_support": avg_citation_support >= min_citation_support,
                "noisy_context": avg_noisy_context <= max_noisy_context,
                "weak_evidence_rate": avg_weak_evidence_rate <= max_weak_evidence_rate,
            }
        )
    if has_ranking_quality_metrics:
        checks.update(
            {
                "recall_at_5": avg_recall_at_5 >= min_recall_at_5,
                "ndcg_at_5": avg_ndcg_at_5 >= min_ndcg_at_5,
                "weak_ranking_rate": avg_weak_ranking_rate <= max_weak_ranking_rate,
            }
        )
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "metrics": {
            "dataset_pass_rate": float(dataset_report.get("pass_rate") or 0.0),
            "avg_supported_rate": avg_supported_rate,
            "avg_topical_rate": avg_topical_rate,
            "avg_grounding": avg_grounding,
            "avg_mismatch": avg_mismatch,
            "avg_citation_support": avg_citation_support,
            "avg_noisy_context": avg_noisy_context,
            "avg_weak_evidence_rate": avg_weak_evidence_rate,
            "avg_recall_at_5": avg_recall_at_5,
            "avg_ndcg_at_5": avg_ndcg_at_5,
            "avg_weak_ranking_rate": avg_weak_ranking_rate,
            "run_log_metrics_available": has_run_log_metrics,
            "context_quality_metrics_available": has_context_quality_metrics,
            "ranking_quality_metrics_available": has_ranking_quality_metrics,
        },
        "thresholds": {
            "min_pass_rate": min_pass_rate,
            "min_supported_rate": min_supported_rate,
            "min_topical_rate": min_topical_rate,
            "min_grounding": min_grounding,
            "max_mismatch": max_mismatch,
            "min_citation_support": min_citation_support,
            "max_noisy_context": max_noisy_context,
            "max_weak_evidence_rate": max_weak_evidence_rate,
            "min_recall_at_5": min_recall_at_5,
            "min_ndcg_at_5": min_ndcg_at_5,
            "max_weak_ranking_rate": max_weak_ranking_rate,
        },
    }
