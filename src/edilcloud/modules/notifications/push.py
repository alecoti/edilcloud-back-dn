from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from datetime import timedelta
from datetime import timezone as datetime_timezone
from pathlib import Path

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from edilcloud.modules.notifications.models import (
    Notification,
    NotificationDevice,
    NotificationPushDelivery,
    NotificationPushDeliveryStatus,
)


logger = logging.getLogger(__name__)

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_FCM_CACHE_KEY = "notifications:fcm:access-token"
_INVALID_TOKEN_CODES = {"UNREGISTERED", "INVALID_ARGUMENT"}


class NotificationPushError(Exception):
    def __init__(self, message: str = "", *, code: str = "") -> None:
        super().__init__(message)
        self.code = (code or "").strip().upper()


class NotificationPushInvalidToken(NotificationPushError):
    pass


def push_enabled() -> bool:
    return bool(getattr(settings, "FCM_PUSH_ENABLED", False) and _load_service_account_info())


def _load_service_account_info() -> dict | None:
    raw_json = getattr(settings, "FCM_SERVICE_ACCOUNT_JSON", "")
    if raw_json:
        for candidate in (raw_json,):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        try:
            decoded = base64.b64decode(raw_json).decode("utf-8")
            return json.loads(decoded)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("FCM_SERVICE_ACCOUNT_JSON non valido, push disabilitate.")
            return None

    raw_path = getattr(settings, "FCM_SERVICE_ACCOUNT_FILE", "").strip()
    if not raw_path:
        return None

    try:
        return json.loads(Path(raw_path).read_text(encoding="utf-8"))
    except OSError:
        logger.warning("FCM_SERVICE_ACCOUNT_FILE non trovato: %s", raw_path)
    except json.JSONDecodeError:
        logger.warning("FCM_SERVICE_ACCOUNT_FILE non contiene JSON valido: %s", raw_path)
    return None


def _fcm_project_id(service_account_info: dict) -> str:
    project_id = (getattr(settings, "FCM_PROJECT_ID", "") or "").strip()
    if project_id:
        return project_id
    return str(service_account_info.get("project_id") or "").strip()


def _cached_access_token() -> str | None:
    cached = cache.get(_FCM_CACHE_KEY)
    if not isinstance(cached, dict):
        return None
    token = str(cached.get("token") or "").strip()
    expires_at_raw = str(cached.get("expires_at") or "").strip()
    if not token or not expires_at_raw:
        return None
    try:
        expires_at = datetime.fromisoformat(expires_at_raw)
    except ValueError:
        return None
    if timezone.is_naive(expires_at):
        expires_at = timezone.make_aware(expires_at, datetime_timezone.utc)
    if expires_at <= timezone.now() + timedelta(seconds=30):
        return None
    return token


def _issue_access_token(service_account_info: dict) -> str:
    cached = _cached_access_token()
    if cached:
        return cached

    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=[_FCM_SCOPE],
    )
    credentials.refresh(Request())
    token = str(credentials.token or "").strip()
    if not token:
        raise NotificationPushError("Token FCM non disponibile.")

    expiry = credentials.expiry
    if expiry is None:
        timeout = 300
        expires_at = timezone.now() + timedelta(seconds=timeout)
    else:
        if timezone.is_naive(expiry):
            expiry = timezone.make_aware(expiry, datetime_timezone.utc)
        timeout = max(60, int((expiry - timezone.now()).total_seconds()) - 60)
        expires_at = expiry

    cache.set(
        _FCM_CACHE_KEY,
        {
            "token": token,
            "expires_at": expires_at.isoformat(),
        },
        timeout=timeout,
    )
    return token


def _safe_payload_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _file_url(file_field) -> str | None:
    if not file_field:
        return None
    try:
        url = file_field.url
    except ValueError:
        return None
    if str(url).startswith("http://") or str(url).startswith("https://"):
        return str(url)
    base_url = str(getattr(settings, "BACKEND_PUBLIC_URL", "") or "").rstrip("/")
    if base_url and str(url).startswith("/"):
        return f"{base_url}{url}"
    return str(url)


def _notification_image_url(notification: Notification) -> str:
    raw_image = str(notification.data.get("image_url") or "").strip()
    if raw_image:
        return raw_image

    sender_profile = notification.sender_profile
    if sender_profile is not None:
        return (
            _file_url(getattr(sender_profile, "photo", None))
            or _file_url(getattr(getattr(sender_profile, "user", None), "photo", None))
            or _file_url(getattr(getattr(sender_profile, "workspace", None), "logo", None))
            or ""
        )

    sender_user = notification.sender_user
    if sender_user is not None:
        return _file_url(getattr(sender_user, "photo", None)) or ""

    return ""


def build_push_data_payload(notification: Notification) -> dict[str, str]:
    target_tab = str(notification.data.get("target_tab") or "").strip().lower()
    target_doc = str(notification.data.get("target_doc") or "").strip()
    content_type = (notification.content_type or "").strip().lower()

    if not target_tab:
        if content_type in {"task", "activity", "post", "comment"}:
            target_tab = "task"
        elif content_type in {"document", "folder"}:
            target_tab = "docs"
        elif content_type == "team":
            target_tab = "team"
        else:
            target_tab = "overview"

    payload = {
        "notification_id": _safe_payload_value(notification.id),
        "event_id": _safe_payload_value(notification.event_id),
        "profile_id": _safe_payload_value(notification.recipient_profile_id),
        "kind": _safe_payload_value(notification.kind),
        "subject": _safe_payload_value(notification.subject),
        "body": _safe_payload_value(notification.body),
        "project_id": _safe_payload_value(notification.project_id),
        "task_id": _safe_payload_value(notification.task_id),
        "activity_id": _safe_payload_value(notification.activity_id),
        "post_id": _safe_payload_value(notification.post_id),
        "comment_id": _safe_payload_value(notification.comment_id),
        "folder_id": _safe_payload_value(notification.folder_id),
        "document_id": _safe_payload_value(notification.document_id),
        "object_id": _safe_payload_value(notification.object_id),
        "content_type": _safe_payload_value(content_type),
        "target_tab": _safe_payload_value(target_tab),
        "target_doc": _safe_payload_value(target_doc),
        "category": _safe_payload_value(notification.data.get("category")),
        "image_url": _safe_payload_value(_notification_image_url(notification)),
    }

    if notification.project_id:
        href = f"/dashboard/cantieri/{notification.project_id}/{target_tab}"
        query_parts = []
        if notification.activity_id:
            query_parts.append(f"activity={notification.activity_id}")
        if notification.post_id:
            query_parts.append(f"post={notification.post_id}")
        if notification.comment_id:
            query_parts.append(f"comment={notification.comment_id}")
        if notification.id:
            query_parts.append(f"notify={notification.id}")
        if target_doc:
            query_parts.append(f"doc={target_doc}")
        if query_parts:
            href = f"{href}?{'&'.join(query_parts)}"
        payload["href"] = href

    return payload


def _notification_text(notification: Notification) -> tuple[str, str]:
    title = (notification.subject or "").strip() or "Nuova notifica"
    body = (notification.body or "").strip()
    if not body:
        body = "Apri la notifica per vedere i dettagli."
    return title[:120], body[:240]


def _build_fcm_message(*, device: NotificationDevice, notification: Notification) -> dict:
    title, body = _notification_text(notification)
    image_url = _notification_image_url(notification)
    notification_payload = {
        "title": title,
        "body": body,
    }
    if image_url:
        notification_payload["image"] = image_url

    return {
        "message": {
            "token": device.token,
            "notification": notification_payload,
            "data": build_push_data_payload(notification),
            "android": {
                "priority": "high",
                "notification": {
                    "channel_id": getattr(settings, "FCM_ANDROID_CHANNEL_ID", "edilcloud_notifications"),
                    "click_action": "FLUTTER_NOTIFICATION_CLICK",
                },
            },
            "apns": {
                "headers": {
                    "apns-priority": "10",
                },
                "payload": {
                    "aps": {
                        "sound": "default",
                        "content-available": 1,
                    },
                },
            },
        }
    }


def _push_url(project_id: str) -> str:
    return f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"


def _extract_fcm_error_code(data: dict) -> str:
    error = data.get("error")
    if not isinstance(error, dict):
        return ""
    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict):
                code = str(detail.get("errorCode") or "").strip().upper()
                if code:
                    return code
    return str(error.get("status") or "").strip().upper()


def _send_push(*, device: NotificationDevice, notification: Notification) -> str | None:
    service_account_info = _load_service_account_info()
    if not service_account_info:
        return

    project_id = _fcm_project_id(service_account_info)
    if not project_id:
        raise NotificationPushError("FCM_PROJECT_ID non configurato.")

    access_token = _issue_access_token(service_account_info)
    try:
        response = httpx.post(
            _push_url(project_id),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json=_build_fcm_message(device=device, notification=notification),
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise NotificationPushError(str(exc)) from exc
    if response.status_code >= 200 and response.status_code < 300:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            provider_message_id = str(payload.get("name") or "").strip()
            return provider_message_id or None
        return None

    payload = {}
    try:
        payload = response.json()
    except ValueError:
        payload = {}

    error_code = _extract_fcm_error_code(payload)
    message = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
    message = message or f"FCM error {response.status_code}"
    if error_code in _INVALID_TOKEN_CODES:
        raise NotificationPushInvalidToken(message, code=error_code)
    raise NotificationPushError(message, code=error_code)


def _register_delivery_attempt(*, notification: Notification, device: NotificationDevice) -> tuple[NotificationPushDelivery, dict]:
    payload_snapshot = build_push_data_payload(notification)
    now = timezone.now()
    delivery, _ = NotificationPushDelivery.objects.get_or_create(
        notification=notification,
        device=device,
        defaults={
            "status": NotificationPushDeliveryStatus.PENDING,
            "attempt_count": 0,
            "payload_snapshot": payload_snapshot,
        },
    )
    NotificationPushDelivery.objects.filter(id=delivery.id).update(
        status=NotificationPushDeliveryStatus.PENDING,
        attempt_count=F("attempt_count") + 1,
        last_attempt_at=now,
        delivered_at=None,
        payload_snapshot=payload_snapshot,
        failed_at=None,
        error_code="",
        error_message="",
        provider_message_id="",
        updated_at=now,
    )
    delivery.refresh_from_db()
    return delivery, payload_snapshot


def _mark_delivery_sent(*, delivery_id: int, provider_message_id: str | None = None) -> None:
    now = timezone.now()
    NotificationPushDelivery.objects.filter(id=delivery_id).update(
        status=NotificationPushDeliveryStatus.SENT,
        delivered_at=now,
        failed_at=None,
        error_code="",
        error_message="",
        provider_message_id=(provider_message_id or "").strip(),
        updated_at=now,
    )


def _mark_delivery_failed(
    *,
    delivery_id: int,
    status: str,
    error_code: str = "",
    error_message: str = "",
) -> None:
    now = timezone.now()
    NotificationPushDelivery.objects.filter(id=delivery_id).update(
        status=status,
        failed_at=now,
        error_code=(error_code or "").strip().upper()[:64],
        error_message=(error_message or "").strip()[:255],
        provider_message_id="",
        updated_at=now,
    )


def dispatch_notification_push(notification: Notification) -> int:
    if not push_enabled():
        return 0

    recipient_user_id = getattr(notification.recipient_profile, "user_id", None)
    devices = list(
        NotificationDevice.objects.filter(
            **(
                {"user_id": recipient_user_id}
                if recipient_user_id
                else {"profile_id": notification.recipient_profile_id}
            ),
            is_active=True,
            push_enabled=True,
        )
    )
    if not devices:
        return 0

    now = timezone.now()
    sent = 0
    for device in devices:
        delivery, _ = _register_delivery_attempt(notification=notification, device=device)
        try:
            provider_message_id = _send_push(device=device, notification=notification)
        except NotificationPushInvalidToken as exc:
            _mark_delivery_failed(
                delivery_id=delivery.id,
                status=NotificationPushDeliveryStatus.INVALID_TOKEN,
                error_code=exc.code,
                error_message=str(exc),
            )
            NotificationDevice.objects.filter(id=device.id).update(
                is_active=False,
                last_push_error=str(exc)[:255],
                last_push_error_at=now,
                updated_at=now,
            )
        except NotificationPushError as exc:
            _mark_delivery_failed(
                delivery_id=delivery.id,
                status=NotificationPushDeliveryStatus.FAILED,
                error_code=exc.code,
                error_message=str(exc),
            )
            NotificationDevice.objects.filter(id=device.id).update(
                last_push_error=str(exc)[:255],
                last_push_error_at=now,
                updated_at=now,
            )
            logger.warning(
                "Push notification non inviata per device %s: %s",
                device.id,
                exc,
            )
        else:
            sent += 1
            _mark_delivery_sent(
                delivery_id=delivery.id,
                provider_message_id=provider_message_id,
            )
            NotificationDevice.objects.filter(id=device.id).update(
                last_push_sent_at=now,
                last_push_error="",
                last_push_error_at=None,
                updated_at=now,
            )
    return sent
