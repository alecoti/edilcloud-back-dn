from __future__ import annotations

import hashlib
from typing import Any

from edilcloud.platform.test_center_issues import build_test_center_issues


ACTION_LIMIT = 100


def _action_id(issue: dict[str, Any]) -> str:
    raw = "remediation:{issue_id}:{category}:{platform}:{target}".format(
        issue_id=issue.get("id"),
        category=issue.get("category"),
        platform=issue.get("platform"),
        target=issue.get("target"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _action_state(issue: dict[str, Any]) -> str:
    automation = issue.get("automation") if isinstance(issue.get("automation"), dict) else {}
    state = str(automation.get("state") or "blocked")
    if state == "candidate":
        return "ready_for_dry_run"
    if state == "manual_review_required":
        return "needs_human_review"
    return "blocked"


def _risk_level(issue: dict[str, Any]) -> str:
    category = str(issue.get("category") or "")
    severity = str(issue.get("severity") or "")
    if category in {"performance", "runtime-budget"}:
        return "high"
    if severity == "critical":
        return "medium"
    return "low"


def _objective(issue: dict[str, Any]) -> str:
    category = str(issue.get("category") or "")
    platform = str(issue.get("platform") or "piattaforma")
    if category == "quality":
        return f"Riportare la quality suite {platform} in stato pass."
    if category == "performance":
        return "Isolare e correggere la regressione evidenziata dal load test."
    if category == "runtime-budget":
        return "Riportare la route fuori soglia entro il runtime budget."
    if category == "instrumentation":
        return f"Collegare segnali e artefatti mancanti per {platform}."
    return "Preparare una remediation verificabile per la issue."


def _preconditions(issue: dict[str, Any]) -> list[str]:
    preconditions = [
        "Issue normalizzata disponibile e associata a una sorgente tecnica.",
        "Log e artifact della sorgente consultabili dalla dashboard.",
    ]
    if issue.get("suggested_commands"):
        preconditions.append("Comandi suggeriti presenti e rilanciabili in ambiente controllato.")
    if issue.get("automation", {}).get("blocked_by"):
        preconditions.append("Blocchi dichiarati risolti o accettati da un operatore.")
    return preconditions


def _plan(issue: dict[str, Any]) -> list[dict[str, Any]]:
    category = str(issue.get("category") or "")
    base_steps = [
        {
            "order": 1,
            "kind": "inspect",
            "label": "Aprire la sorgente tecnica collegata alla issue.",
            "requires_human": False,
        },
        {
            "order": 2,
            "kind": "evidence",
            "label": "Validare evidenze, log e comandi falliti prima di agire.",
            "requires_human": True,
        },
    ]
    if category == "quality":
        base_steps.extend(
            [
                {
                    "order": 3,
                    "kind": "rerun",
                    "label": "Rilanciare la quality suite della piattaforma in modalita dry-run.",
                    "requires_human": False,
                },
                {
                    "order": 4,
                    "kind": "fix-scope",
                    "label": "Limitare eventuali modifiche ai moduli indicati da stderr/stdout.",
                    "requires_human": True,
                },
            ]
        )
    elif category in {"performance", "runtime-budget"}:
        base_steps.extend(
            [
                {
                    "order": 3,
                    "kind": "profile",
                    "label": "Riprodurre la route o il profilo di carico che genera la regressione.",
                    "requires_human": False,
                },
                {
                    "order": 4,
                    "kind": "diagnose",
                    "label": "Isolare query, cache, serializzazione o dipendenza esterna coinvolta.",
                    "requires_human": True,
                },
            ]
        )
    elif category == "instrumentation":
        base_steps.extend(
            [
                {
                    "order": 3,
                    "kind": "connect",
                    "label": "Collegare il runner mancante e produrre un artifact normalizzato.",
                    "requires_human": True,
                },
                {
                    "order": 4,
                    "kind": "verify",
                    "label": "Verificare che la piattaforma passi da pending a live.",
                    "requires_human": False,
                },
            ]
        )
    base_steps.append(
        {
            "order": len(base_steps) + 1,
            "kind": "confirm",
            "label": "Ripetere la verifica e aggiornare la issue solo dopo esito verde.",
            "requires_human": False,
        }
    )
    return base_steps


def _success_criteria(issue: dict[str, Any]) -> list[str]:
    category = str(issue.get("category") or "")
    if category == "quality":
        return [
            "La quality suite torna in stato pass.",
            "I comandi falliti non producono stderr bloccante.",
            "La dashboard aggiorna la issue rimuovendo la criticita.",
        ]
    if category == "performance":
        return [
            "Il load test torna in stato pass.",
            "Failure ratio entro soglia.",
            "p95 e p99 rientrano nei budget dichiarati.",
        ]
    if category == "runtime-budget":
        return [
            "La regola runtime budget torna in stato pass.",
            "La route impattata non compare piu tra i failing budget.",
        ]
    if category == "instrumentation":
        return [
            "La piattaforma espone un artifact recente.",
            "Lo stato data_state passa a live.",
        ]
    return ["La issue non viene piu generata dal Test Center."]


def _action_from_issue(issue: dict[str, Any]) -> dict[str, Any]:
    automation = issue.get("automation") if isinstance(issue.get("automation"), dict) else {}
    suggested_commands = [
        str(command)
        for command in issue.get("suggested_commands", [])
        if isinstance(command, str) and command
    ]
    safe_actions = [
        str(action)
        for action in automation.get("safe_actions", [])
        if isinstance(action, str) and action
    ]
    blocked_by = [
        str(blocker)
        for blocker in automation.get("blocked_by", [])
        if isinstance(blocker, str) and blocker
    ]
    return {
        "id": _action_id(issue),
        "issue_id": issue.get("id"),
        "state": _action_state(issue),
        "mode": "dry_run",
        "risk": _risk_level(issue),
        "platform": issue.get("platform"),
        "target": issue.get("target"),
        "category": issue.get("category"),
        "title": "Remediation: " + str(issue.get("title") or "issue"),
        "objective": _objective(issue),
        "source_issue": {
            "id": issue.get("id"),
            "title": issue.get("title"),
            "severity": issue.get("severity"),
            "summary": issue.get("summary"),
            "source": issue.get("source"),
        },
        "preconditions": _preconditions(issue),
        "plan": _plan(issue),
        "allowed_operations": safe_actions,
        "verification_commands": suggested_commands,
        "blocked_by": blocked_by,
        "success_criteria": _success_criteria(issue),
        "audit": {
            "will_modify_code": False,
            "will_touch_production": False,
            "requires_operator_approval": bool(blocked_by) or _risk_level(issue) != "low",
        },
    }


def _sort_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state_rank = {"ready_for_dry_run": 0, "needs_human_review": 1, "blocked": 2}
    risk_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        actions,
        key=lambda action: (
            state_rank.get(str(action.get("state")), 9),
            risk_rank.get(str(action.get("risk")), 9),
            str(action.get("platform") or ""),
        ),
    )


def build_test_center_actions() -> dict[str, Any]:
    issues_payload = build_test_center_issues()
    actions = [
        _action_from_issue(issue)
        for issue in issues_payload.get("issues", [])
        if isinstance(issue, dict)
    ]
    sorted_actions = _sort_actions(actions)[:ACTION_LIMIT]
    return {
        "generated_at": issues_payload["generated_at"],
        "status": "ok" if not sorted_actions else "attention",
        "summary": {
            "total": len(sorted_actions),
            "ready_for_dry_run": sum(
                action["state"] == "ready_for_dry_run" for action in sorted_actions
            ),
            "needs_human_review": sum(
                action["state"] == "needs_human_review" for action in sorted_actions
            ),
            "blocked": sum(action["state"] == "blocked" for action in sorted_actions),
            "high_risk": sum(action["risk"] == "high" for action in sorted_actions),
        },
        "actions": sorted_actions,
    }


def build_test_center_action_detail(action_id: str) -> dict[str, Any] | None:
    for action in build_test_center_actions()["actions"]:
        if action.get("id") == action_id:
            return action
    return None
