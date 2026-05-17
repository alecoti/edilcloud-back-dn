from __future__ import annotations

import hashlib
from typing import Any

from edilcloud.platform.test_center import build_test_center_overview


ISSUE_LIMIT = 100


def _issue_id(*parts: object) -> str:
    raw = ":".join(str(part) for part in parts if part is not None)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _severity_from_status(status: str) -> str:
    if status == "critical" or status == "fail":
        return "critical"
    if status in {"warning", "partial", "skipped"}:
        return "warning"
    if status == "no_data":
        return "info"
    return "info"


def _quality_title(platform: str, target: str | None = None) -> str:
    if platform == "flutter" and target:
        label = "iOS" if target == "ios" else target
        return f"Flutter {label} quality suite non verde"
    if platform == "frontend-next":
        return "Frontend Next quality suite non verde"
    if platform == "backend":
        return "Backend quality suite non verde"
    return f"{platform} quality suite non verde"


def _quality_issue(
    report: dict[str, Any],
    *,
    platform: str,
    target: str | None = None,
) -> dict[str, Any] | None:
    status = str(report.get("status") or "no_data")
    if status in {"pass", "no_data"}:
        return None

    commands = [
        command for command in report.get("commands", []) if isinstance(command, dict)
    ]
    failing_commands = [
        command
        for command in commands
        if str(command.get("status") or "") in {"fail", "warning", "skipped"}
    ]
    command_labels = [
        str(command.get("label") or command.get("key") or "command")
        for command in failing_commands[:3]
    ]
    evidence = list(report.get("focus", []))
    if command_labels:
        evidence.append("Comandi da verificare: " + ", ".join(command_labels) + ".")
    if report.get("source_path"):
        evidence.append(f"Artefatto: {report['source_path']}.")

    suggested_commands = [
        str(command.get("command") or "")
        for command in failing_commands
        if command.get("command")
    ][:4]

    if not suggested_commands:
        if platform == "backend":
            suggested_commands = [
                r"..\venv\Scripts\ruff.exe check src scripts tests",
                r"..\venv\Scripts\pytest.exe",
            ]
        elif platform == "frontend-next":
            suggested_commands = ["pnpm exec eslint", "pnpm build"]
        elif platform == "flutter" and target == "android":
            suggested_commands = [
                "flutter analyze",
                "flutter test",
                "flutter build apk --debug",
            ]
        elif platform == "flutter" and target == "ios":
            suggested_commands = [
                "flutter analyze",
                "flutter test",
                "flutter build ios --debug",
            ]

    return {
        "id": _issue_id("quality", platform, target, report.get("id"), status),
        "status": "open",
        "severity": _severity_from_status(status),
        "platform": platform,
        "target": target,
        "category": "quality",
        "title": _quality_title(platform, target),
        "summary": (
            "{failed}/{commands} comandi falliti, {skipped} saltati.".format(
                failed=report.get("summary", {}).get("failed", 0),
                commands=report.get("summary", {}).get("commands", 0),
                skipped=report.get("summary", {}).get("skipped", 0),
            )
        ),
        "detected_at": report.get("generated_at"),
        "source": {
            "kind": "quality-report",
            "run_id": report.get("id"),
            "path": report.get("source_path"),
        },
        "evidence": evidence[:6],
        "playbook": [
            "Aprire il dettaglio quality e leggere stderr/stdout dei comandi non verdi.",
            "Riprodurre localmente il primo comando fallito.",
            "Applicare una correzione limitata al modulo indicato dai log.",
            "Rilanciare la suite quality della piattaforma e poi la build completa se tocca contratti condivisi.",
        ],
        "suggested_commands": suggested_commands,
        "automation": {
            "state": "manual_review_required" if status == "fail" else "candidate",
            "safe_actions": ["rerun_quality_suite"],
            "blocked_by": [] if status != "fail" else ["serve conferma umana prima di modifiche codice"],
        },
    }


def _loadtest_issue(report: dict[str, Any]) -> dict[str, Any] | None:
    status = str(report.get("status") or "no_data")
    if status in {"pass", "no_data"}:
        return None

    summary = report.get("summary", {})
    evidence = list(report.get("focus", []))
    evidence.append(
        "Failure ratio {ratio}, p95 {p95} ms, p99 {p99} ms.".format(
            ratio=summary.get("failure_ratio", 0.0),
            p95=summary.get("p95_ms", 0.0),
            p99=summary.get("p99_ms", 0.0),
        )
    )
    if report.get("source_path"):
        evidence.append(f"Artefatto: {report['source_path']}.")

    return {
        "id": _issue_id("loadtest", report.get("id"), status),
        "status": "open",
        "severity": "critical" if status == "fail" else "info",
        "platform": "backend",
        "target": None,
        "category": "performance",
        "title": "Ultimo load test non verde",
        "summary": (
            "{requests} richieste, {failures} failure, p95 {p95} ms.".format(
                requests=summary.get("requests", 0),
                failures=summary.get("failures", 0),
                p95=summary.get("p95_ms", 0.0),
            )
        ),
        "detected_at": report.get("generated_at"),
        "source": {
            "kind": "loadtest-report",
            "run_id": report.get("id"),
            "path": report.get("source_path"),
        },
        "evidence": evidence[:6],
        "playbook": [
            "Aprire il dettaglio Locust e ordinare endpoint per p95/failure.",
            "Confrontare la route lenta con runtime budget e metriche HTTP live.",
            "Isolare query, serializzazione, cache o dipendenza esterna coinvolta.",
            "Rilanciare lo stesso profilo Locust dopo la correzione.",
        ],
        "suggested_commands": [
            r"..\venv\Scripts\python.exe scripts\run_locust_suite.py --profile read-heavy --headless",
            r"..\venv\Scripts\python.exe scripts\run_locust_suite.py --profile mixed-crud --headless",
        ],
        "automation": {
            "state": "manual_review_required" if status == "fail" else "candidate",
            "safe_actions": ["rerun_loadtest_suite"],
            "blocked_by": ["serve analisi umana prima di tuning prestazionale"],
        },
    }


def _runtime_budget_issues(performance: dict[str, Any]) -> list[dict[str, Any]]:
    runtime_budget = performance.get("runtime_budget", {})
    issues: list[dict[str, Any]] = []
    for rule in runtime_budget.get("failing", []):
        if not isinstance(rule, dict):
            continue
        key = str(rule.get("key") or "runtime-budget")
        issues.append(
            {
                "id": _issue_id("runtime-budget", key, rule.get("p95_ms")),
                "status": "open",
                "severity": "critical",
                "platform": "backend",
                "target": None,
                "category": "runtime-budget",
                "title": f"Runtime budget fuori soglia: {key}",
                "summary": (
                    "p95 {p95} ms su limite {max_p95} ms, error ratio {error_ratio}.".format(
                        p95=rule.get("p95_ms", 0.0),
                        max_p95=rule.get("max_p95_ms", 0.0),
                        error_ratio=rule.get("error_ratio", 0.0),
                    )
                ),
                "detected_at": None,
                "source": {
                    "kind": "runtime-budget",
                    "run_id": None,
                    "path": rule.get("path_pattern"),
                },
                "evidence": [
                    "Route candidate: "
                    + ", ".join(str(path) for path in rule.get("matched_paths", [])[:3]),
                    "Metodo {method}, pattern {pattern}.".format(
                        method=rule.get("method", "GET"),
                        pattern=rule.get("path_pattern", "-"),
                    ),
                    "Campione: {requests} richieste su minimo {min_requests}.".format(
                        requests=rule.get("requests", 0),
                        min_requests=rule.get("min_requests", 0),
                    ),
                ],
                "playbook": [
                    "Aprire route con p95 piu alto nella vista performance.",
                    "Controllare query database, serializzazione risposta e cache.",
                    "Aggiungere un test di regressione prestazionale se la route e core.",
                    "Verificare runtime budget dopo la correzione.",
                ],
                "suggested_commands": [
                    r"..\venv\Scripts\pytest.exe tests/test_health.py",
                ],
                "automation": {
                    "state": "manual_review_required",
                    "safe_actions": ["refresh_runtime_budget"],
                    "blocked_by": ["serve analisi umana della route impattata"],
                },
            }
        )
    return issues


def _platform_instrumentation_issues(
    platforms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for platform in platforms:
        if platform.get("data_state") != "pending_instrumentation":
            continue
        key = str(platform.get("key") or "unknown")
        issues.append(
            {
                "id": _issue_id("instrumentation", key),
                "status": "open",
                "severity": "info",
                "platform": key,
                "target": None,
                "category": "instrumentation",
                "title": f"Strumentazione incompleta: {platform.get('label', key)}",
                "summary": str(platform.get("summary") or "Segnale non ancora collegato."),
                "detected_at": platform.get("last_seen_at"),
                "source": {
                    "kind": "platform-state",
                    "run_id": None,
                    "path": None,
                },
                "evidence": list(platform.get("focus", []))[:6]
                or ["Nessun artefatto recente disponibile per questa piattaforma."],
                "playbook": [
                    "Collegare il runner quality della piattaforma.",
                    "Pubblicare output JSON normalizzato in .tmp/test-center/quality.",
                    "Verificare che la dashboard passi da pending a live.",
                ],
                "suggested_commands": [],
                "automation": {
                    "state": "blocked",
                    "safe_actions": [],
                    "blocked_by": ["manca ancora una sorgente dati stabile"],
                },
            }
        )
    return issues


def _sort_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    return sorted(
        issues,
        key=lambda issue: (
            severity_rank.get(str(issue.get("severity")), 9),
            str(issue.get("platform") or ""),
            str(issue.get("category") or ""),
        ),
    )


def build_test_center_issues() -> dict[str, Any]:
    overview = build_test_center_overview()
    issues: list[dict[str, Any]] = []
    issues.extend(_runtime_budget_issues(overview["performance"]))
    issues.extend(_platform_instrumentation_issues(overview["platforms"]))

    loadtest_issue = _loadtest_issue(overview["loadtests"])
    if loadtest_issue is not None:
        issues.append(loadtest_issue)

    quality = overview["quality"]
    quality_reports = [
        (quality["backend"], "backend", None),
        (quality["frontend-next"], "frontend-next", None),
        (quality["flutter"]["android"], "flutter", "android"),
        (quality["flutter"]["ios"], "flutter", "ios"),
    ]
    for report, platform, target in quality_reports:
        issue = _quality_issue(report, platform=platform, target=target)
        if issue is not None:
            issues.append(issue)

    sorted_issues = _sort_issues(issues)[:ISSUE_LIMIT]
    return {
        "generated_at": overview["generated_at"],
        "status": "ok" if not sorted_issues else "attention",
        "summary": {
            "total": len(sorted_issues),
            "critical": sum(issue["severity"] == "critical" for issue in sorted_issues),
            "warning": sum(issue["severity"] == "warning" for issue in sorted_issues),
            "info": sum(issue["severity"] == "info" for issue in sorted_issues),
            "autofix_candidates": sum(
                issue.get("automation", {}).get("state") == "candidate"
                for issue in sorted_issues
            ),
            "manual_review_required": sum(
                issue.get("automation", {}).get("state") == "manual_review_required"
                for issue in sorted_issues
            ),
        },
        "issues": sorted_issues,
    }
