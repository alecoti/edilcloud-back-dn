from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test end-to-end dei flussi assistant e drafting passando dal frontend Next locale."
    )
    parser.add_argument("--frontend-base-url", default="http://localhost:3000")
    parser.add_argument("--email", default="admin@admin.it")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--project-id", type=int, default=0)
    return parser.parse_args()


def expect_ok(response: requests.Response, label: str) -> Any:
    if not response.ok:
        raise RuntimeError(f"{label} failed with HTTP {response.status_code}: {response.text[:600]}")
    if not response.text.strip():
        return None
    return response.json()


def parse_sse_events(raw_stream: str) -> dict[str, bool]:
    return {
        "meta": "event: meta" in raw_stream,
        "delta": "event: delta" in raw_stream,
        "done": "event: done" in raw_stream,
    }


def choose_project(projects: list[dict[str, Any]], requested_project_id: int) -> dict[str, Any]:
    if requested_project_id:
        for project in projects:
            if int(project.get("id") or 0) == requested_project_id:
                return project
        raise RuntimeError(f"Project id {requested_project_id} non trovato nella sessione utente.")
    if not projects:
        raise RuntimeError("Nessun progetto disponibile per l'utente corrente.")
    return projects[0]


def main() -> int:
    args = parse_args()
    base_url = args.frontend_base_url.rstrip("/")
    session = requests.Session()

    login_response = session.post(
        f"{base_url}/api/auth/login",
        json={"usernameOrEmail": args.email, "password": args.password},
        timeout=30,
    )
    login_payload = expect_ok(login_response, "login")

    projects_response = session.get(f"{base_url}/api/projects", timeout=30)
    projects_payload = expect_ok(projects_response, "projects list")
    if not isinstance(projects_payload, list):
        raise RuntimeError("La lista progetti ha un formato inatteso.")
    project = choose_project(projects_payload, args.project_id)
    project_id = int(project["id"])

    assistant_state_response = session.get(
        f"{base_url}/api/projects/{project_id}/assistant",
        timeout=30,
    )
    assistant_state = expect_ok(assistant_state_response, "assistant state")

    overview_response = session.get(
        f"{base_url}/api/projects/{project_id}/overview",
        timeout=30,
    )
    overview = expect_ok(overview_response, "project overview")
    tasks = overview.get("tasks") or []
    if not tasks:
        raise RuntimeError("Overview priva di task: impossibile completare lo smoke test drafting.")
    task = tasks[0]
    activities = task.get("activities") or []
    activity = activities[0] if activities else None

    stream_response = session.post(
        f"{base_url}/api/projects/{project_id}/assistant/stream",
        json={
            "message": "Dammi un riepilogo tecnico delle criticita aperte e dei documenti utili per le fondazioni.",
            "forceSync": False,
        },
        timeout=90,
    )
    raw_stream = stream_response.text
    if not stream_response.ok:
        raise RuntimeError(
            f"assistant stream failed with HTTP {stream_response.status_code}: {raw_stream[:600]}"
        )
    sse_events = parse_sse_events(raw_stream)
    if not all(sse_events.values()):
        raise RuntimeError(f"assistant stream incompleto: {json.dumps(sse_events)}")

    excerpts: list[str] = []
    for post in (overview.get("alertPosts") or [])[:2]:
        text = (post or {}).get("text")
        if isinstance(text, str) and text.strip():
            excerpts.append(text.strip())
    excerpts.append(
        "Nota vocale: completata pulizia fronte nord e verifica armature, da controllare interferenza con linea drenante."
    )

    drafting_payload = {
        "documentType": "rapportino",
        "locale": "it",
        "sourceLanguage": "it",
        "context": {
            "taskId": task.get("id"),
            "taskName": task.get("name") or "Task",
            "activityId": activity.get("id") if isinstance(activity, dict) else None,
            "activityTitle": activity.get("title") if isinstance(activity, dict) else None,
            "dateFrom": "2026-04-04",
            "dateTo": "2026-04-04",
        },
        "evidence": {
            "postCount": len(overview.get("recentPosts") or []),
            "commentCount": sum(len(post.get("comment_set") or []) for post in (overview.get("recentPosts") or [])),
            "mediaCount": sum(len(post.get("media_set") or []) for post in (overview.get("recentPosts") or [])),
            "documentCount": len(overview.get("documents") or []),
            "photoCount": len(overview.get("photos") or []),
            "excerpts": excerpts[:3],
        },
        "operatorInput": {
            "notes": "Preparare un rapportino tecnico della giornata focalizzato su fondazioni, criticita e mezzi impiegati.",
            "voiceOriginal": "Pulizia fronte nord completata, armature viste, da verificare linea drenante lato nord.",
            "voiceItalian": "La squadra ha completato la pulizia del fronte nord e il controllo preliminare delle armature. Resta da verificare una possibile interferenza con la linea drenante sul lato nord.",
        },
    }
    drafting_response = session.post(
        f"{base_url}/api/projects/{project_id}/documents/ai-draft",
        json=drafting_payload,
        timeout=120,
    )
    drafting_result = expect_ok(drafting_response, "ai-draft")

    autocomplete_response = session.post(
        f"{base_url}/api/projects/{project_id}/documents/ai-draft/autocomplete",
        json={
            "documentType": "rapportino",
            "locale": "it",
            "draftText": drafting_result.get("markdown", "")[:1200],
        },
        timeout=90,
    )
    autocomplete_result = expect_ok(autocomplete_response, "ai-draft autocomplete")

    result = {
        "login_status": login_payload.get("status"),
        "project": {
            "id": project_id,
            "name": project.get("name"),
        },
        "assistant_state": {
            "assistant_ready": (assistant_state.get("stats") or {}).get("assistant_ready"),
            "source_count": (assistant_state.get("stats") or {}).get("source_count"),
            "chunk_count": (assistant_state.get("stats") or {}).get("chunk_count"),
            "embedding_model": (assistant_state.get("stats") or {}).get("embedding_model"),
        },
        "assistant_stream": {
            "events": sse_events,
            "snippet": raw_stream[:260],
        },
        "drafting": {
            "title": drafting_result.get("title"),
            "provider": drafting_result.get("provider"),
            "model": drafting_result.get("model"),
            "fallback": drafting_result.get("fallback"),
            "snippet": (drafting_result.get("markdown") or "")[:260],
        },
        "autocomplete": {
            "provider": autocomplete_result.get("provider"),
            "model": autocomplete_result.get("model"),
            "fallback": autocomplete_result.get("fallback"),
            "snippet": (autocomplete_result.get("completion_text") or "")[:220],
        },
    }
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
