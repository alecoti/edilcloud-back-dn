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
