import uuid

from django.conf import settings
from django.db import models

from edilcloud.modules.workspaces.models import Profile, TimestampedModel


class Notification(TimestampedModel):
    recipient_profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="sent_notifications",
        null=True,
        blank=True,
    )
    sender_profile = models.ForeignKey(
        Profile,
        on_delete=models.SET_NULL,
        related_name="authored_notifications",
        null=True,
        blank=True,
    )
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=64, blank=True)
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    sender_company_name = models.CharField(max_length=255, blank=True)
    sender_position = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=64, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    project_id = models.PositiveIntegerField(null=True, blank=True)
    task_id = models.PositiveIntegerField(null=True, blank=True)
    activity_id = models.PositiveIntegerField(null=True, blank=True)
    post_id = models.PositiveIntegerField(null=True, blank=True)
    comment_id = models.PositiveIntegerField(null=True, blank=True)
    folder_id = models.PositiveIntegerField(null=True, blank=True)
    document_id = models.PositiveIntegerField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("recipient_profile", "read_at")),
            models.Index(fields=("recipient_profile", "created_at")),
            models.Index(fields=("kind",)),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def __str__(self) -> str:
        return f"{self.subject} -> profile:{self.recipient_profile_id}"


class NotificationDevicePlatform(models.TextChoices):
    ANDROID = "android", "Android"
    IOS = "ios", "iOS"
    WEB = "web", "Web"
    UNKNOWN = "unknown", "Unknown"


class NotificationPushDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    INVALID_TOKEN = "invalid_token", "Invalid token"
    SKIPPED = "skipped", "Skipped"


class NotificationDevice(TimestampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_devices",
    )
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="notification_devices",
    )
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(
        max_length=16,
        choices=NotificationDevicePlatform.choices,
        default=NotificationDevicePlatform.UNKNOWN,
    )
    installation_id = models.CharField(max_length=128, blank=True)
    device_name = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=16, blank=True)
    timezone = models.CharField(max_length=64, blank=True)
    app_version = models.CharField(max_length=64, blank=True)
    push_enabled = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_registered_at = models.DateTimeField(null=True, blank=True)
    last_push_sent_at = models.DateTimeField(null=True, blank=True)
    last_push_error_at = models.DateTimeField(null=True, blank=True)
    last_push_error = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("-last_seen_at", "-id")
        indexes = [
            models.Index(fields=("profile", "is_active")),
            models.Index(fields=("user", "is_active")),
            models.Index(fields=("installation_id",)),
        ]

    @property
    def token_suffix(self) -> str:
        return self.token[-10:] if len(self.token) > 10 else self.token

    def __str__(self) -> str:
        return f"{self.platform}:{self.token_suffix} -> profile:{self.profile_id}"


class NotificationPushDelivery(TimestampedModel):
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="push_deliveries",
    )
    device = models.ForeignKey(
        NotificationDevice,
        on_delete=models.CASCADE,
        related_name="push_deliveries",
    )
    status = models.CharField(
        max_length=24,
        choices=NotificationPushDeliveryStatus.choices,
        default=NotificationPushDeliveryStatus.PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.CharField(max_length=255, blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    payload_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-last_attempt_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("notification", "device"),
                name="notifications_push_delivery_unique_notification_device",
            )
        ]
        indexes = [
            models.Index(fields=("notification", "status")),
            models.Index(fields=("device", "status")),
            models.Index(fields=("last_attempt_at",)),
        ]

    def __str__(self) -> str:
        return (
            f"notification:{self.notification_id} -> "
            f"device:{self.device_id} ({self.status})"
        )
