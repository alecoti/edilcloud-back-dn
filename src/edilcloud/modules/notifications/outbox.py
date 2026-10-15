"""Durable push delivery, bounded immediate execution and a recoverable worker."""
import logging
import random
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import BoundedSemaphore

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import Notification, NotificationPushDelivery, NotificationPushJob

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="edilcloud-push")
_slots = BoundedSemaphore(16)
_TRANSIENT = {"", "NETWORK_ERROR", "UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED", "RESOURCE_EXHAUSTED", "UNAUTHENTICATED", "UNKNOWN"}


def enqueue_notification_push(notification: Notification):
    enabled = bool(getattr(settings, "FCM_PUSH_ENABLED", False))
    NotificationPushJob.objects.get_or_create(notification=notification, defaults={
        "state": "pending" if enabled else "skipped", "last_error": "" if enabled else "FCM_DISABLED",
    })
    if enabled:
        transaction.on_commit(lambda: _kick(notification.id), robust=True)


def _kick(notification_id):
    if not _slots.acquire(blocking=False):
        return  # The persistent worker picks up pending jobs, including after a restart.
    def run():
        close_old_connections()
        try:
            process_push_job(notification_id)
        except Exception:
            logger.exception("notifications.push.job_failed", extra={"notification_id": notification_id})
        finally:
            close_old_connections()
            _slots.release()
    try:
        _executor.submit(run)
    except RuntimeError:
        _slots.release()


def due_push_jobs(limit=100):
    now = timezone.now()
    return NotificationPushJob.objects.filter(
        Q(state__in=("pending", "retry"), next_attempt_at__lte=now) |
        Q(state="processing", locked_until__lt=now)
    ).order_by("next_attempt_at", "notification_id").values_list("notification_id", flat=True)[:limit]


def process_push_job(notification_id):
    from .push import dispatch_notification_push, push_enabled

    now, lease = timezone.now(), uuid.uuid4()
    eligible = Q(state__in=("pending", "retry"), next_attempt_at__lte=now) | Q(state="processing", locked_until__lt=now)
    if not push_enabled():
        NotificationPushJob.objects.filter(notification_id=notification_id).filter(eligible).update(
            state="retry", last_error="FCM_CONFIG_UNAVAILABLE", next_attempt_at=now+timedelta(seconds=60),
            locked_until=None, lease=None, updated_at=now,
        )
        return False
    claimed = NotificationPushJob.objects.filter(notification_id=notification_id).filter(eligible).update(
        state="processing", locked_until=now + timedelta(minutes=10), lease=lease,
        attempt_count=F("attempt_count") + 1, updated_at=now,
    )
    if not claimed:
        return False
    job = NotificationPushJob.objects.select_related("notification__recipient_profile__user", "notification__sender_profile").get(notification_id=notification_id)
    state, reason, delay = "complete", "", 60
    try:
        notification = job.notification
        actor = notification.sender_user_id or getattr(notification.sender_profile, "user_id", None)
        if actor and actor == notification.recipient_profile.user_id:
            state, reason = "skipped", "SELF_AUTHORED"
        elif not notification.recipient_profile.is_active or not notification.recipient_profile.workspace.is_active or (notification.recipient_profile.user_id and not notification.recipient_profile.user.is_active):
            state, reason = "skipped", "RECIPIENT_INACTIVE"
        elif not _project_push_allowed(notification):
            state, reason = "skipped", "PROJECT_ACCESS_OR_PREFERENCES"
        elif notification.created_at < now - timedelta(hours=24):
            state, reason = "skipped", "EXPIRED"
        else:
            dispatch_notification_push(job.notification)
            deliveries = list(NotificationPushDelivery.objects.filter(notification_id=notification_id).values("status", "error_code", "retry_after_seconds"))
            transient = [item for item in deliveries if item["status"] == "failed" and item["error_code"] in _TRANSIENT]
            if not deliveries or transient:
                state, reason = "retry", (transient[0]["error_code"] or "PROVIDER_ERROR") if transient else "NO_ACTIVE_DEVICE"
                delay = max([item["retry_after_seconds"] for item in transient] or [0])
            elif not any(item["status"] == "sent" for item in deliveries):
                state, reason = "failed", "NO_SUCCESSFUL_DELIVERY"
    except Exception as error:
        state, reason = "retry", type(error).__name__[:64]
    if state == "retry":
        if job.attempt_count >= 8:
            state = "failed"
        delay = max(delay, min(6 * 3600, 60 * 2 ** min(job.attempt_count - 1, 8))) + random.randint(0, 15)
    NotificationPushJob.objects.filter(notification_id=notification_id, lease=lease, state="processing").update(
        state=state, last_error=reason, locked_until=None, lease=None,
        next_attempt_at=timezone.now() + timedelta(seconds=delay), updated_at=timezone.now(),
    )
    return True


def _project_push_allowed(notification):
    if not notification.project_id:
        return True
    from edilcloud.modules.projects.notification_preferences import project_notification_allowed
    return project_notification_allowed(profile=notification.recipient_profile,
        project_id=notification.project_id, kind=notification.kind, push=True)
