import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


def main_profile_photo_upload_to(_instance, filename: str) -> str:
    return f"identity/users/photos/{filename}"


class UserManager(BaseUserManager):
    use_in_migrations = True

    def build_unique_username(self, base_username: str) -> str:
        normalized = (base_username or "user").strip() or "user"
        candidate = normalized
        index = 1
        while self.model.objects.filter(username__iexact=candidate).exists():
            index += 1
            candidate = f"{normalized}{index}"
        return candidate

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("The email field must be set.")

        email = self.normalize_email(email)
        username = self.build_unique_username(extra_fields.get("username") or email.split("@", 1)[0])
        extra_fields["email"] = email
        extra_fields["username"] = username

        user = self.model(**extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_active", True)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=64, unique=True, null=True, blank=True, default=None)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    language = models.CharField(max_length=8, default="it")
    photo = models.FileField(upload_to=main_profile_photo_upload_to, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = UserManager()

    class Meta:
        ordering = ("id",)

    @property
    def primary_role(self) -> str:
        return "owner"

    @property
    def main_profile_id(self) -> int:
        return self.id

    @property
    def auth_extra(self) -> dict:
        return {
            "profile": {
                "id": self.main_profile_id,
                "role": self.primary_role,
                "company": None,
            }
        }

    def __str__(self) -> str:
        return self.email


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuthProvider(models.TextChoices):
    EMAIL = "email", "Email"
    GOOGLE = "google", "Google"


class AccessSession(TimestampedModel):
    flow_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(db_index=True)
    provider = models.CharField(max_length=16, choices=AuthProvider.choices)
    code_hash = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return f"{self.email} ({self.provider})"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_active(self) -> bool:
        return self.consumed_at is None and not self.is_expired


class AuthTokenSession(TimestampedModel):
    session_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="auth_sessions",
    )
    current_access_jti = models.CharField(max_length=128, blank=True, default="")
    current_refresh_jti = models.CharField(max_length=128, blank=True, default="")
    current_profile_id = models.IntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoke_reason = models.CharField(max_length=64, blank=True)
    created_ip = models.GenericIPAddressField(null=True, blank=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_refreshed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and not self.is_expired


class PasswordResetSession(TimestampedModel):
    flow_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_sessions",
    )
    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=255)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_active(self) -> bool:
        return self.consumed_at is None and not self.is_expired
