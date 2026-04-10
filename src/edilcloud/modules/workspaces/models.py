import secrets

from django.conf import settings
from django.db import models
from django.utils.text import slugify


def workspace_logo_upload_to(_instance, filename: str) -> str:
    return f"workspaces/logos/{filename}"


def profile_photo_upload_to(_instance, filename: str) -> str:
    return f"workspaces/profiles/photos/{filename}"


def generate_uidb36() -> str:
    return secrets.token_urlsafe(9).replace("-", "").replace("_", "").lower()


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def generate_invite_code() -> str:
    return f"{secrets.randbelow(10000):04d}-{secrets.randbelow(10000):04d}"


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class WorkspaceRole(models.TextChoices):
    OWNER = "o", "Owner"
    DELEGATE = "d", "Delegate"
    MANAGER = "m", "Manager"
    WORKER = "w", "Worker"


class Workspace(TimestampedModel):
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    workspace_type = models.CharField(max_length=64, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    website = models.URLField(blank=True)
    vat_number = models.CharField(max_length=32, blank=True)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=16, blank=True)
    logo = models.FileField(upload_to=workspace_logo_upload_to, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "id")

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self.build_unique_slug(self.name)
        super().save(*args, **kwargs)

    @classmethod
    def build_unique_slug(cls, value: str) -> str:
        base_slug = slugify(value)[:230] or "workspace"
        candidate = base_slug
        index = 1
        while cls.objects.filter(slug=candidate).exists():
            index += 1
            suffix = f"-{index}"
            candidate = f"{base_slug[: max(1, 230 - len(suffix))]}{suffix}"
        return candidate


class Profile(TimestampedModel):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="profiles",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_profiles",
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=1,
        choices=WorkspaceRole.choices,
        default=WorkspaceRole.WORKER,
    )
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    language = models.CharField(max_length=8, default="it")
    position = models.CharField(max_length=255, blank=True)
    photo = models.FileField(upload_to=profile_photo_upload_to, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("workspace_id", "id")
        constraints = [
            models.UniqueConstraint(fields=("workspace", "user"), name="unique_workspace_user"),
        ]

    def __str__(self) -> str:
        return f"{self.member_name} ({self.workspace.name})"

    @property
    def member_name(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email


class WorkspaceInvite(TimestampedModel):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invites",
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_workspace_invites",
        null=True,
        blank=True,
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="accepted_workspace_invites",
        null=True,
        blank=True,
    )
    email = models.EmailField()
    role = models.CharField(
        max_length=1,
        choices=WorkspaceRole.choices,
        default=WorkspaceRole.WORKER,
    )
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    position = models.CharField(max_length=255, blank=True)
    invite_code = models.CharField(max_length=9, unique=True, blank=True)
    uidb36 = models.CharField(max_length=32, unique=True, default=generate_uidb36)
    token = models.CharField(max_length=64, unique=True, default=generate_token)
    expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    refused_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return f"{self.email} -> {self.workspace.name}"

    @property
    def is_pending(self) -> bool:
        return self.accepted_at is None

    def save(self, *args, **kwargs):
        if not self.invite_code:
            self.invite_code = self.build_unique_invite_code()
        super().save(*args, **kwargs)

    @classmethod
    def build_unique_invite_code(cls) -> str:
        candidate = generate_invite_code()
        while cls.objects.filter(invite_code=candidate).exists():
            candidate = generate_invite_code()
        return candidate


class AccessRequestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REFUSED = "refused", "Refused"


class WorkspaceAccessRequest(TimestampedModel):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="access_requests",
    )
    requested_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="workspace_access_requests",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_workspace_access_requests",
        null=True,
        blank=True,
    )
    email = models.EmailField()
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    language = models.CharField(max_length=8, default="it")
    position = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)
    photo_path = models.CharField(max_length=512, blank=True)
    picture_url = models.URLField(blank=True)
    request_token = models.CharField(max_length=64, unique=True, default=generate_token)
    status = models.CharField(
        max_length=16,
        choices=AccessRequestStatus.choices,
        default=AccessRequestStatus.PENDING,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    refused_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("workspace", "status")),
            models.Index(fields=("email", "status")),
        ]

    def __str__(self) -> str:
        return f"{self.email} -> {self.workspace.name} [{self.status}]"

    @property
    def is_pending(self) -> bool:
        return self.status == AccessRequestStatus.PENDING
