"""Realtime ticket issuance and event fanout services."""

from __future__ import annotations

import secrets
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from edilcloud.modules.workspaces.services import get_user_profile, select_default_profile


REALTIME_TICKET_CACHE_PREFIX = "realtime:ticket"


def _ticket_cache_key(ticket: str) -> str:
    return f"{REALTIME_TICKET_CACHE_PREFIX}:{ticket}"


def resolve_realtime_profile(user, claims: dict):
    profile_id = claims.get("main_profile")
    if isinstance(profile_id, str) and profile_id.isdigit():
        profile_id = int(profile_id)
    if isinstance(profile_id, int):
        profile = get_user_profile(user, profile_id)
        if profile is not None:
            return profile
    return select_default_profile(user)


def _serialize_ticket_payload(
    *,
    user_id: int,
    profile_id: int,
    channel: str,
    project_id: int | None = None,
) -> dict:
    return {
        "user_id": user_id,
        "profile_id": profile_id,
        "channel": channel,
        "project_id": project_id,
        "issued_at": timezone.now().isoformat(),
    }


def issue_realtime_ticket(
    *,
    user_id: int,
    profile_id: int,
    channel: str,
    project_id: int | None = None,
) -> tuple[str, str]:
    """Create a short-lived websocket ticket stored in cache for subsequent socket validation."""
    ticket = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(seconds=settings.REALTIME_TICKET_TTL_SECONDS)
    payload = _serialize_ticket_payload(
        user_id=user_id,
        profile_id=profile_id,
        channel=channel,
        project_id=project_id,
    )
    cache.set(_ticket_cache_key(ticket), payload, timeout=settings.REALTIME_TICKET_TTL_SECONDS)
    return ticket, expires_at.isoformat()


def read_realtime_ticket(ticket: str) -> dict | None:
    payload = cache.get(_ticket_cache_key(ticket))
    return payload if isinstance(payload, dict) else None


def validate_realtime_ticket(
    *,
    ticket: str,
    expected_channel: str,
    expected_project_id: int | None = None,
) -> dict:
    payload = read_realtime_ticket(ticket)
    if payload is None:
        raise ValueError("Ticket realtime non valido o scaduto.")
    if payload.get("channel") != expected_channel:
        raise ValueError("Canale realtime non valido.")
    if expected_channel == "project" and payload.get("project_id") != expected_project_id:
        raise ValueError("Ticket realtime non valido per questo progetto.")
    return payload


def build_notification_socket_record(*, user, claims: dict) -> dict | None:
    profile = resolve_realtime_profile(user, claims)
    if profile is None:
        return None

    ticket, expires_at = issue_realtime_ticket(
        user_id=user.id,
        profile_id=profile.id,
        channel="notifications",
    )
    return {
        "path": "/ws/realtime/notifications/",
        "ticket": ticket,
        "expires_at": expires_at,
        "profile_id": profile.id,
        "project_id": None,
    }


def build_project_socket_record(*, user, claims: dict, project_id: int) -> dict | None:
    profile = resolve_realtime_profile(user, claims)
    if profile is None:
        return None

    ticket, expires_at = issue_realtime_ticket(
        user_id=user.id,
        profile_id=profile.id,
        channel="project",
        project_id=project_id,
    )
    return {
        "path": f"/ws/realtime/projects/{project_id}/",
        "ticket": ticket,
        "expires_at": expires_at,
        "profile_id": profile.id,
        "project_id": project_id,
    }


def build_notification_realtime_session(*, user, claims: dict) -> dict:
    notifications = build_notification_socket_record(user=user, claims=claims)
    return {
        "enabled": notifications is not None,
        "notifications": notifications,
    }


def build_project_realtime_session(*, user, claims: dict, project_id: int) -> dict:
    project_socket = build_project_socket_record(user=user, claims=claims, project_id=project_id)
    notifications = build_notification_socket_record(user=user, claims=claims)
    return {
        "enabled": project_socket is not None,
        "project": project_socket,
        "notifications": notifications,
    }


def notification_group_name(profile_id: int) -> str:
    return f"notifications.profile.{profile_id}"


def project_group_name(project_id: int) -> str:
    return f"projects.{project_id}"


def publish_notification_event(*, profile_id: int, payload: dict) -> None:
    """Broadcast a notification event to all sockets subscribed for the profile."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        notification_group_name(profile_id),
        {"type": "realtime.event", "payload": payload},
    )


def publish_project_event(*, project_id: int, payload: dict) -> None:
    """Broadcast a project-scoped event to all sockets subscribed for the project."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        project_group_name(project_id),
        {"type": "realtime.event", "payload": payload},
    )
