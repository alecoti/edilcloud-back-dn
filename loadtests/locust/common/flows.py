from __future__ import annotations

from dataclasses import dataclass, field
from itertools import count
import random
import time
from typing import Any

from locust.clients import HttpSession

from loadtests.locust.common.config import LocustRunConfig


_USER_COUNTER = count(1)


@dataclass
class ScenarioState:
    email: str
    project_id: int | None = None
    task_id: int | None = None
    cached_post_ids: list[int] = field(default_factory=list)
    created_post_ids: list[int] = field(default_factory=list)
    created_comment_ids: list[int] = field(default_factory=list)
    authenticated: bool = False


def next_user_email(prefix: str) -> str:
    return f"{prefix}.{next(_USER_COUNTER):04d}@example.com"


def _json_payload(response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def login(client: HttpSession, *, state: ScenarioState, config: LocustRunConfig) -> bool:
    with client.post(
        "/api/auth/login",
        json={"usernameOrEmail": state.email, "password": config.password},
        name="auth.login",
        catch_response=True,
    ) as response:
        if response.status_code == 200:
            state.authenticated = True
            response.success()
            return True
        response.failure(f"Login fallito per {state.email}: {response.status_code}")
        return False


def resolve_project_id(
    client: HttpSession,
    *,
    state: ScenarioState,
    config: LocustRunConfig,
    record_name: str = "projects.list",
) -> int | None:
    if config.project_id > 0:
        state.project_id = config.project_id
        return state.project_id
    if state.project_id is not None:
        return state.project_id

    with client.get("/api/projects", name=record_name, catch_response=True) as response:
        if response.status_code != 200:
            response.failure(f"Lista progetti non disponibile: {response.status_code}")
            return None
        payload = _json_payload(response)
        items = payload if isinstance(payload, list) else []
        if not items and isinstance(payload, dict):
            raw_items = payload.get("items") or payload.get("value")
            items = raw_items if isinstance(raw_items, list) else []
        if not items:
            response.failure("Nessun progetto disponibile per il load test.")
            return None
        try:
            state.project_id = int(items[0]["id"])
        except (KeyError, TypeError, ValueError):
            response.failure("Payload progetti non valido.")
            return None
        response.success()
        return state.project_id


def refresh_task_id(client: HttpSession, *, state: ScenarioState) -> int | None:
    if state.project_id is None:
        return None
    with client.get(
        f"/api/projects/{state.project_id}/tasks",
        name="project.tasks",
        catch_response=True,
    ) as response:
        if response.status_code != 200:
            response.failure(f"Task progetto non disponibili: {response.status_code}")
            return None
        payload = _json_payload(response)
        items = payload if isinstance(payload, list) else []
        if not items and isinstance(payload, dict):
            raw_items = payload.get("items") or payload.get("value")
            items = raw_items if isinstance(raw_items, list) else []
        if not items:
            response.failure("Nessun task disponibile per scenari di dettaglio.")
            return None
        try:
            state.task_id = int(items[0]["id"])
        except (KeyError, TypeError, ValueError):
            response.failure("Payload task non valido.")
            return None
        response.success()
        return state.task_id


def refresh_feed_cache(client: HttpSession, *, state: ScenarioState, limit: int = 10) -> list[int]:
    with client.get(f"/api/feed?limit={limit}&offset=0", name="feed.list", catch_response=True) as response:
        if response.status_code != 200:
            response.failure(f"Feed non disponibile: {response.status_code}")
            return state.cached_post_ids
        payload = _json_payload(response)
        items = payload if isinstance(payload, list) else []
        if isinstance(payload, dict):
            raw_items = payload.get("items") or payload.get("results")
            items = raw_items if isinstance(raw_items, list) else items

        post_ids: list[int] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                post_ids.append(int(item["id"]))
            except (KeyError, TypeError, ValueError):
                continue
        state.cached_post_ids = post_ids
        response.success()
        return state.cached_post_ids


def bootstrap_user(client: HttpSession, *, state: ScenarioState, config: LocustRunConfig) -> bool:
    if not login(client, state=state, config=config):
        return False
    if resolve_project_id(client, state=state, config=config, record_name="bootstrap.projects") is None:
        return False
    refresh_task_id(client, state=state)
    refresh_feed_cache(client, state=state)
    return True


def search_global(client: HttpSession, *, config: LocustRunConfig) -> None:
    term = random.choice(config.search_terms)
    client.get(
        f"/api/search/global?q={term}&limit=6",
        name="search.global",
    )


def create_task_post(client: HttpSession, *, state: ScenarioState) -> int | None:
    if state.task_id is None:
        refresh_task_id(client, state=state)
    if state.task_id is None:
        return None

    with client.post(
        f"/api/tasks/{state.task_id}/posts",
        files={
            "text": (None, f"[locust] aggiornamento operativo {time.time():.6f}"),
            "post_kind": (None, "work-progress"),
            "is_public": (None, "false"),
            "alert": (None, "false"),
        },
        name="task.posts.create",
        catch_response=True,
    ) as response:
        if response.status_code != 201:
            response.failure(f"Creazione post fallita: {response.status_code}")
            return None
        payload = _json_payload(response)
        post_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(post_id, int):
            response.failure("Creazione post senza id valido.")
            return None
        state.created_post_ids.append(post_id)
        state.cached_post_ids = [
            post_id,
            *[value for value in state.cached_post_ids if value != post_id],
        ]
        response.success()
        return post_id


def create_post_comment(client: HttpSession, *, state: ScenarioState) -> int | None:
    if state.created_post_ids:
        post_id = state.created_post_ids[-1]
    elif state.cached_post_ids:
        post_id = state.cached_post_ids[0]
    else:
        refresh_feed_cache(client, state=state)
        post_id = state.cached_post_ids[0] if state.cached_post_ids else None
    if post_id is None:
        return None

    with client.post(
        f"/api/posts/{post_id}/comments",
        files={
            "text": (None, f"[locust] commento operativo {time.time():.6f}"),
            "is_public": (None, "false"),
            "alert": (None, "false"),
        },
        name="post.comments.create",
        catch_response=True,
    ) as response:
        if response.status_code != 201:
            response.failure(f"Creazione commento fallita: {response.status_code}")
            return None
        payload = _json_payload(response)
        comment_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(comment_id, int):
            response.failure("Creazione commento senza id valido.")
            return None
        state.created_comment_ids.append(comment_id)
        response.success()
        return comment_id


def delete_comment(client: HttpSession, *, state: ScenarioState) -> None:
    if not state.created_comment_ids:
        return
    comment_id = state.created_comment_ids.pop()
    with client.delete(
        f"/api/comments/{comment_id}",
        name="comment.delete",
        catch_response=True,
    ) as response:
        if response.status_code == 204:
            response.success()
            return
        state.created_comment_ids.append(comment_id)
        response.failure(f"Delete commento fallita: {response.status_code}")


def delete_post(client: HttpSession, *, state: ScenarioState) -> None:
    if not state.created_post_ids:
        return
    post_id = state.created_post_ids.pop()
    with client.delete(
        f"/api/posts/{post_id}",
        name="post.delete",
        catch_response=True,
    ) as response:
        if response.status_code == 204:
            state.cached_post_ids = [value for value in state.cached_post_ids if value != post_id]
            response.success()
            return
        state.created_post_ids.append(post_id)
        response.failure(f"Delete post fallita: {response.status_code}")


def cleanup_created_content(client: HttpSession, *, state: ScenarioState) -> None:
    while state.created_comment_ids:
        delete_comment(client, state=state)
    while state.created_post_ids:
        delete_post(client, state=state)
