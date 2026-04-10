from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from edilcloud.modules.notifications.models import Notification


def file_url(file_field) -> str | None:
    if not file_field:
        return None
    try:
        return file_field.url
    except ValueError:
        return None


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
) -> Notification:
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

    from edilcloud.platform.realtime.services import publish_notification_event

    publish_notification_event(
        profile_id=recipient_profile.id,
        payload=build_notification_event(notification),
    )
    return notification


def list_notifications(*, user, claims: dict, limit: int = 80) -> dict:
    profile = resolve_notification_profile(user=user, claims=claims)
    if profile is None:
        return {"unread_count": 0, "results": []}

    safe_limit = min(max(int(limit or 80), 1), 100)
    queryset = (
        Notification.objects.select_related(
            "recipient_profile",
            "sender_user",
            "sender_profile",
            "sender_profile__workspace",
            "sender_profile__user",
        )
        .filter(recipient_profile=profile)
        .order_by("-created_at", "-id")
    )
    return {
        "unread_count": queryset.filter(read_at__isnull=True).count(),
        "results": [serialize_notification(item) for item in queryset[:safe_limit]],
    }


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

    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at", "updated_at"])

    return serialize_notification(notification)


@transaction.atomic
def mark_all_notifications_read(*, user, claims: dict) -> dict:
    profile = resolve_notification_profile(user=user, claims=claims)
    if profile is None:
        return {"ok": True, "updated": 0}

    updated = (
        Notification.objects.filter(recipient_profile=profile, read_at__isnull=True)
        .update(read_at=timezone.now(), updated_at=timezone.now())
    )
    return {"ok": True, "updated": updated}
