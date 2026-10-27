"""Notification adapter for the shared document access predicate."""

from edilcloud.modules.elaborati.document_access import (
    UUID_PATTERN as UUID_PATTERN,
    visible_document_records as visible_document_notifications,
)

def notification_delivery_allowed(notification):
    if notification.recipient_profile_id is None:
        return False
    from .models import Notification

    return visible_document_notifications(
        Notification.objects.filter(pk=notification.pk),
        profile=notification.recipient_profile,
    ).exists()
