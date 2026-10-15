from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from edilcloud.modules.notifications.models import (
    Notification,
    NotificationDevice,
    NotificationDevicePlatform,
)
from edilcloud.modules.notifications.outbox import enqueue_notification_push


def file_url(file_field) -> str | None:
    from edilcloud.modules.workspaces.services import file_url as preview_file_url
    return preview_file_url(file_field, image_pixels=320)


def resolve_notification_profile(*, user, claims: dict):
    from edilcloud.platform.realtime.services import resolve_realtime_profile

    return resolve_realtime_profile(user, claims)


def serialize_notification_sender(notification: Notification) -> dict | None:
    sender_profile = notification.sender_profile
    sender_user = notification.sender_user

    sender_id = None
    first_name = ""
    last_name = ""
    photo = None
    company_name = notification.sender_company_name or None
    position = notification.sender_position or None

    if sender_profile is not None:
        sender_id = sender_profile.id
        first_name = sender_profile.first_name or ""
        last_name = sender_profile.last_name or ""
        photo = file_url(sender_profile.photo) or file_url(getattr(sender_profile.user, "photo", None))
        if not company_name:
            company_name = sender_profile.workspace.name
        if not position:
            position = sender_profile.position or None
    elif sender_user is not None:
        sender_id = sender_user.id
        first_name = sender_user.first_name or ""
        last_name = sender_user.last_name or ""
        photo = file_url(getattr(sender_user, "photo", None))

    if not any([sender_id, first_name, last_name, photo, company_name, position]):
        return None

    return {
        "id": sender_id,
        "first_name": first_name or None,
        "last_name": last_name or None,
        "photo": photo,
        "company_name": company_name,
        "position": position,
    }


def serialize_notification(notification: Notification) -> dict:
    return {
        "id": notification.id,
        "event_id": str(notification.event_id),
        "kind": notification.kind or None,
        "subject": notification.subject,
        "body": notification.body or "",
        "created_at": notification.created_at,
        "read_at": notification.read_at,
        "is_read": notification.is_read,
        "sender": serialize_notification_sender(notification),
        "target": {
            "project_id": notification.project_id,
            "task_id": notification.task_id,
            "activity_id": notification.activity_id,
            "post_id": notification.post_id,
            "comment_id": notification.comment_id,
            "folder_id": notification.folder_id,
            "document_id": notification.document_id,
            "object_id": notification.object_id,
            "content_type": notification.content_type or None,
        },
        "data": notification.data or {},
    }


def build_notification_event(notification: Notification) -> dict:
    sender = serialize_notification_sender(notification)
    return {
        "eventId": str(notification.event_id),
        "channel": "notification",
        "type": "notification.created",
        "timestamp": timezone.now().isoformat(),
        "userId": getattr(notification.recipient_profile, "user_id", None),
        "profileId": notification.recipient_profile_id,
        "projectId": notification.project_id,
        "taskId": notification.task_id,
        "activityId": notification.activity_id,
        "postId": notification.post_id,
        "commentId": notification.comment_id,
        "folderId": notification.folder_id,
        "documentId": notification.document_id,
        "notificationId": notification.id,
        "actor": {
            "id": sender["id"],
            "firstName": sender["first_name"],
            "lastName": sender["last_name"],
            "companyId": notification.sender_profile.workspace_id if notification.sender_profile else None,
            "companyName": sender["company_name"],
        }
        if sender
        else None,
        "data": notification.data or {},
    }


def build_notification_read_event(notification: Notification) -> dict:
    payload = build_notification_event(notification)
    payload["eventId"] = f"{notification.event_id}:read"
    payload["type"] = "notification.read"
    payload["timestamp"] = timezone.now().isoformat()
    payload["data"] = {
        **(notification.data or {}),
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
    }
    return payload


def build_notification_read_all_event(*, profile_id: int, user_id: int | None, updated: int) -> dict:
    return {
        "eventId": f"notification.read_all:{profile_id}:{uuid.uuid4()}",
        "channel": "notification",
        "type": "notification.read_all",
        "timestamp": timezone.now().isoformat(),
        "userId": user_id,
        "profileId": profile_id,
        "projectId": None,
        "taskId": None,
        "activityId": None,
        "postId": None,
        "commentId": None,
        "folderId": None,
        "documentId": None,
        "notificationId": None,
        "actor": None,
        "data": {"updated": int(updated or 0)},
    }


@transaction.atomic
def create_notification(
    *,
    recipient_profile,
    subject: str,
    body: str = "",
    kind: str = "",
    sender_user=None,
    sender_profile=None,
    sender_company_name: str = "",
    sender_position: str = "",
    content_type: str = "",
    object_id: int | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
    activity_id: int | None = None,
    post_id: int | None = None,
    comment_id: int | None = None,
    folder_id: int | None = None,
    document_id: int | None = None,
    data: dict | None = None,
) -> Notification | None:
    # A person may belong to the same project through several workspace profiles.
    # Excluding only the actor profile still sends their own action to their phone.
    actor_user_id = getattr(sender_user, "id", None) or getattr(sender_profile, "user_id", None)
    if (sender_profile is not None and sender_profile.id == recipient_profile.id) or (
        actor_user_id and actor_user_id == recipient_profile.user_id
    ):
        return None
    notification = Notification.objects.create(
        recipient_profile=recipient_profile,
        sender_user=sender_user,
        sender_profile=sender_profile,
        subject=(subject or "").strip() or "Nuova notifica",
        body=(body or "").strip(),
        kind=(kind or "").strip(),
        sender_company_name=(sender_company_name or "").strip(),
        sender_position=(sender_position or "").strip(),
        content_type=(content_type or "").strip(),
        object_id=object_id,
        project_id=project_id,
        task_id=task_id,
        activity_id=activity_id,
        post_id=post_id,
        comment_id=comment_id,
        folder_id=folder_id,
        document_id=document_id,
        data=data or {},
    )

    def _publish_notification_side_effects() -> None:
        from edilcloud.platform.realtime.services import publish_notification_event

        publish_notification_event(
            profile_id=recipient_profile.id,
            payload=build_notification_event(notification),
        )

    transaction.on_commit(_publish_notification_side_effects, robust=True)
    enqueue_notification_push(notification)
    return notification


def _normalize_device_platform(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {
        NotificationDevicePlatform.ANDROID,
        NotificationDevicePlatform.IOS,
        NotificationDevicePlatform.WEB,
    }:
        return normalized
    return NotificationDevicePlatform.UNKNOWN


def serialize_notification_device(device: NotificationDevice) -> dict:
    return {
        "id": device.id,
        "token_suffix": device.token_suffix,
        "platform": device.platform,
        "installation_id": device.installation_id or "",
        "device_name": device.device_name or "",
        "locale": device.locale or "",
        "timezone": device.timezone or "",
        "app_version": device.app_version or "",
        "push_enabled": device.push_enabled,
        "is_active": device.is_active,
    }


@transaction.atomic
def register_notification_device(
    *,
    user,
    claims: dict,
    token: str,
    platform: str = "",
    installation_id: str = "",
    device_name: str = "",
    locale: str = "",
    timezone_name: str = "",
    app_version: str = "",
    push_enabled: bool = True,
) -> dict:
    profile = resolve_notification_profile(user=user, claims=claims)
    if profile is None:
        raise ValueError("Profilo notifiche non disponibile.")

    clean_token = (token or "").strip()
    if len(clean_token) < 32:
        raise ValueError("Token push non valido.")

    now = timezone.now()
    device = NotificationDevice.objects.filter(token=clean_token).first()
    if device is None:
        device = NotificationDevice.objects.create(
            user=user,
            profile=profile,
            token=clean_token,
            platform=_normalize_device_platform(platform),
            installation_id=(installation_id or "").strip(),
            device_name=(device_name or "").strip(),
            locale=(locale or "").strip(),
            timezone=(timezone_name or "").strip(),
            app_version=(app_version or "").strip(),
            push_enabled=bool(push_enabled),
            is_active=True,
            last_seen_at=now,
            last_registered_at=now,
        )
    else:
        device.user = user
        device.profile = profile
        device.platform = _normalize_device_platform(platform)
        device.installation_id = (installation_id or "").strip()
        device.device_name = (device_name or "").strip()
        device.locale = (locale or "").strip()
        device.timezone = (timezone_name or "").strip()
        device.app_version = (app_version or "").strip()
        device.push_enabled = bool(push_enabled)
        device.is_active = True
        device.last_seen_at = now
        device.last_registered_at = now
        device.save()

    if device.installation_id:
        NotificationDevice.objects.filter(
            installation_id=device.installation_id,
        ).exclude(id=device.id).update(
            is_active=False,
            updated_at=now,
        )

    raw_session_id = claims.get("sid") or claims.get("session_id")
    try:
        session_id = uuid.UUID(str(raw_session_id)) if raw_session_id else None
    except (ValueError, TypeError):
        session_id = None
    if device.auth_session_id != session_id:
        device.auth_session_id = session_id
        device.save(update_fields=["auth_session_id", "updated_at"])

    return serialize_notification_device(device)


@transaction.atomic
def unregister_notification_device(
    *,
    user,
    claims: dict,
    token: str | None = None,
    installation_id: str | None = None,
) -> dict:
    clean_token = (token or "").strip()
    clean_installation_id = (installation_id or "").strip()
    if not clean_token and not clean_installation_id:
        raise ValueError("Token o installation_id richiesti.")

    queryset = NotificationDevice.objects.filter(user=user)
    if clean_token:
        queryset = queryset.filter(token=clean_token)
    if clean_installation_id:
        queryset = queryset.filter(installation_id=clean_installation_id)

    updated = queryset.update(
        is_active=False,
        updated_at=timezone.now(),
    )
    return {"ok": True, "updated": updated}


def visible_notifications_queryset(profile):
    from django.db.models import Q
    queryset = Notification.objects.filter(recipient_profile=profile)
    if profile.user_id:
        queryset = queryset.exclude(Q(sender_user_id=profile.user_id) | Q(sender_profile__user_id=profile.user_id))
    queryset = queryset.exclude(sender_profile_id=profile.id)
    if profile.demo_project_hidden:
        from edilcloud.modules.projects.models import Project

        queryset = queryset.exclude(project_id__in=Project.objects.filter(is_demo_master=True).values("id"))
    return queryset


def list_notifications(*, user, claims: dict, limit: int = 80, count_only: bool = False, offset: int = 0, cursor: str | None = None) -> dict:
    from django.db.models import Q
    from edilcloud.platform.pagination import decode_activity_cursor, encode_activity_cursor

    profile = resolve_notification_profile(user=user, claims=claims)
    if profile is None:
        return {"unread_count": 0, "results": []}

    safe_limit = min(max(int(limit or 80), 1), 100)
    queryset = (
        visible_notifications_queryset(profile).select_related(
            "recipient_profile",
            "sender_user",
            "sender_profile",
            "sender_profile__workspace",
            "sender_profile__user",
        )
        .order_by("-created_at", "-id")
    )
    unread_count = queryset.filter(read_at__isnull=True).count()
    safe_offset = max(int(offset), 0)
    if cursor:
        timestamp, cursor_id = decode_activity_cursor(cursor)
        queryset = queryset.filter(Q(created_at__lt=timestamp) | Q(created_at=timestamp, id__lt=cursor_id))
    items = [] if count_only else list(queryset[(0 if cursor else safe_offset):(0 if cursor else safe_offset) + safe_limit + 1])
    has_more = len(items) > safe_limit
    items = items[:safe_limit]
    return {
        "unread_count": unread_count,
        "results": [serialize_notification(item) for item in items],
        "has_more": has_more,
        "next_offset": safe_offset + safe_limit if has_more else None,
        "next_cursor": encode_activity_cursor(items[-1].created_at, items[-1].id) if has_more else None,
    }


@transaction.atomic
def mark_notifications_read(*, user, claims: dict, notification_ids: list[int]) -> dict:
    profile = resolve_notification_profile(user=user, claims=claims)
    if profile is None:
        raise ValueError("Profilo notifiche non disponibile.")
    ids = {value for value in notification_ids if value > 0}
    if len(ids) > 250:
        raise ValueError("Massimo 250 notifiche per richiesta.")
    queryset = visible_notifications_queryset(profile).filter(id__in=ids)
    read_at = timezone.now()
    updated = queryset.filter(read_at__isnull=True).update(read_at=read_at, updated_at=read_at)
    items = list(queryset.select_related("sender_user", "sender_profile__workspace", "sender_profile__user"))
    result = {
        "results": [serialize_notification(item) for item in items],
        "unread_count": visible_notifications_queryset(profile).filter(read_at__isnull=True).count(),
    }
    if updated:
        payload = build_notification_read_all_event(profile_id=profile.id, user_id=profile.user_id, updated=updated)
        payload["type"] = "notification.read_batch"
        payload["data"].update({"notification_ids": [item.id for item in items], "read_at": read_at.isoformat(), "unread_count": result["unread_count"]})
        transaction.on_commit(lambda: publish_notification_read_batch(profile.id, payload))
    return result


def publish_notification_read_batch(profile_id: int, payload: dict) -> None:
    from edilcloud.platform.realtime.services import publish_notification_event

    publish_notification_event(profile_id=profile_id, payload=payload)


@transaction.atomic
def mark_notification_read(*, user, claims: dict, notification_id: int) -> dict:
    profile = resolve_notification_profile(user=user, claims=claims)
    if profile is None:
        raise ValueError("Profilo notifiche non disponibile.")

    notification = (
        Notification.objects.select_related(
            "sender_user",
            "sender_profile",
            "sender_profile__workspace",
            "sender_profile__user",
        )
        .filter(id=notification_id, recipient_profile=profile)
        .first()
    )
    if notification is None:
        raise ValueError("Notifica non trovata.")

    was_unread = notification.read_at is None
    if was_unread:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])

        def _publish_notification_read_side_effect() -> None:
            from edilcloud.platform.realtime.services import publish_notification_event

            publish_notification_event(
                profile_id=profile.id,
                payload=build_notification_read_event(notification),
            )

        transaction.on_commit(_publish_notification_read_side_effect)

    return {**serialize_notification(notification), "unread_count": visible_notifications_queryset(profile).filter(read_at__isnull=True).count()}


@transaction.atomic
def mark_all_notifications_read(*, user, claims: dict) -> dict:
    profile = resolve_notification_profile(user=user, claims=claims)
    if profile is None:
        return {"ok": True, "updated": 0}

    updated = (
        visible_notifications_queryset(profile).filter(read_at__isnull=True)
        .update(read_at=timezone.now(), updated_at=timezone.now())
    )

    if updated > 0:
        user_id = getattr(profile, "user_id", None)

        def _publish_notification_read_all_side_effect() -> None:
            from edilcloud.platform.realtime.services import publish_notification_event

            publish_notification_event(
                profile_id=profile.id,
                payload=build_notification_read_all_event(
                    profile_id=profile.id,
                    user_id=user_id,
                    updated=updated,
                ),
            )

        transaction.on_commit(_publish_notification_read_all_side_effect)

    return {"ok": True, "updated": updated, "unread_count": visible_notifications_queryset(profile).filter(read_at__isnull=True).count()}
