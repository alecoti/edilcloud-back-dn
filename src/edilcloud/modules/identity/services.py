"""Service layer for identity, session and onboarding workflows."""

import json
import logging
import mimetypes
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import jwt
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone as django_timezone
from django.utils.text import slugify

from edilcloud.modules.identity.models import (
    AccessSession,
    AuthProvider,
    AuthTokenSession,
    PasswordResetSession,
)
from edilcloud.modules.workspaces.models import Profile
from edilcloud.platform.email import send_email_message
from edilcloud.platform.logging import get_request_context
from edilcloud.platform.telemetry import increment_counter


logger = logging.getLogger("edilcloud.auth")

GENERIC_LOGIN_ERROR = "Impossibile effettuare il login con le credenziali fornite."
GENERIC_SESSION_ERROR = "Sessione non valida o scaduta."
GENERIC_PASSWORD_RESET_REQUEST_DETAIL = (
    "Se l'account esiste, ti abbiamo inviato le istruzioni per reimpostare la password."
)
GENERIC_PASSWORD_RESET_CONFIRM_ERROR = "Codice o email non validi."

SUPPORTED_LANGUAGE_CODES = {"it", "en", "fr", "ro", "ru", "ar"}
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def unix_timestamp(value: datetime) -> int:
    return int(value.timestamp())


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def normalize_language(language: str | None) -> str:
    candidate = (language or "it").strip().lower() or "it"
    if candidate in SUPPORTED_LANGUAGE_CODES:
        return candidate
    return "it"


def normalize_phone_number(phone: str | None) -> str:
    """Normalize a phone-like identifier while staying permissive during the fake verification phase."""
    candidate = (phone or "").strip()
    if not candidate:
        return ""

    has_plus_prefix = candidate.startswith("+")
    digits = "".join(character for character in candidate if character.isdigit())
    if 6 <= len(digits) <= 15:
        return f"+{digits}" if has_plus_prefix else digits
    if len(candidate) < 3:
        raise ValueError("Numero di telefono non valido.")
    return candidate[:64]


def file_field_url(file_field) -> str:
    if not file_field:
        return ""
    try:
        return file_field.url
    except ValueError:
        return ""


def normalize_phone_storage_value(phone: str | None) -> str | None:
    normalized_phone = normalize_phone_number(phone)
    return normalized_phone or None


def ensure_unique_main_phone(phone: str | None, *, excluding_user_id: int | None = None) -> str:
    normalized_phone = normalize_phone_number(phone)
    if not normalized_phone:
        return ""

    user_model = get_user_model()
    queryset = user_model.objects.filter(phone=normalized_phone)
    if excluding_user_id is not None:
        queryset = queryset.exclude(id=excluding_user_id)
    if queryset.exists():
        raise ValueError(
            "Questo numero di telefono e gia collegato a un altro main profile. "
            "Scrivi al supporto se hai bisogno di sbloccarlo."
        )
    return normalized_phone


def storage_public_url(path: str | None) -> str:
    if not path:
        return ""
    try:
        return default_storage.url(path)
    except Exception:
        return ""


def delete_storage_path(path: str | None) -> None:
    if not path:
        return
    try:
        if default_storage.exists(path):
            default_storage.delete(path)
    except Exception:
        return


def guess_image_extension(*, filename: str = "", content_type: str = "") -> str:
    guessed_from_type = mimetypes.guess_extension((content_type or "").split(";", 1)[0].strip())
    extension = guessed_from_type or Path(filename or "").suffix.lower() or ".jpg"
    if extension == ".jpe":
        extension = ".jpg"
    if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
        extension = ".jpg"
    return ".jpg" if extension == ".jpeg" else extension


def ensure_storage_parent_directory(path: str) -> None:
    """Create the parent directory when the active storage is filesystem-backed."""
    try:
        absolute_path = Path(default_storage.path(path))
    except Exception:
        return

    try:
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return


def store_onboarding_profile_photo(*, email: str, uploaded_file) -> tuple[str, str]:
    """Persist an uploaded onboarding avatar and return its storage path and public URL."""
    extension = guess_image_extension(
        filename=getattr(uploaded_file, "name", ""),
        content_type=getattr(uploaded_file, "content_type", ""),
    )
    local_part = normalize_email(email).split("@", 1)[0] or "profile"
    path = f"onboarding/profile-photos/{local_part}-{uuid.uuid4().hex}{extension}"
    ensure_storage_parent_directory(path)
    stored_path = default_storage.save(path, uploaded_file)
    return stored_path, storage_public_url(stored_path)


def cache_remote_onboarding_picture(*, email: str, remote_url: str) -> tuple[str, str]:
    """Mirror a third-party avatar locally so the onboarding flow does not depend on external URLs."""
    if not remote_url:
        return "", ""

    try:
        with urlopen(remote_url, timeout=5) as response:
            content = response.read()
            content_type = response.headers.get("Content-Type", "")
    except Exception:
        return "", ""

    if not content:
        return "", ""

    extension = guess_image_extension(
        filename=urlparse(remote_url).path,
        content_type=content_type,
    )
    local_part = normalize_email(email).split("@", 1)[0] or "profile"
    path = f"onboarding/profile-photos/{local_part}-{uuid.uuid4().hex}{extension}"
    ensure_storage_parent_directory(path)
    stored_path = default_storage.save(path, ContentFile(content))
    return stored_path, storage_public_url(stored_path)


def assign_user_photo_from_storage_path(user, *, stored_path: str = "", overwrite: bool = True) -> bool:
    if not stored_path:
        return False
    if user.photo and not overwrite:
        return False
    if not default_storage.exists(stored_path):
        return False
    if user.photo and user.photo.name == stored_path:
        return False

    file_name = Path(stored_path).name or "main-profile-photo.jpg"
    with default_storage.open(stored_path, "rb") as handle:
        user.photo.save(file_name, File(handle), save=True)
    return True


def sync_user_main_identity(
    user,
    *,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    language: str = "it",
    profile_photo_path: str = "",
    remote_picture_url: str = "",
    mark_phone_verified: bool = False,
) -> None:
    normalized_first_name = (first_name or user.first_name or "").strip()
    normalized_last_name = (last_name or user.last_name or "").strip()
    normalized_language = normalize_language(language or user.language or "it")
    normalized_phone = ensure_unique_main_phone(phone, excluding_user_id=user.id) if phone else ""
    stored_phone = normalized_phone or None
    update_fields: list[str] = []

    if normalized_first_name and user.first_name != normalized_first_name:
        user.first_name = normalized_first_name
        update_fields.append("first_name")
    if normalized_last_name and user.last_name != normalized_last_name:
        user.last_name = normalized_last_name
        update_fields.append("last_name")
    if user.language != normalized_language:
        user.language = normalized_language
        update_fields.append("language")
    if user.phone != stored_phone:
        user.phone = stored_phone
        update_fields.append("phone")
        if stored_phone:
            user.phone_verified_at = django_timezone.now()
        else:
            user.phone_verified_at = None
        update_fields.append("phone_verified_at")
    elif stored_phone and mark_phone_verified and user.phone_verified_at is None:
        user.phone_verified_at = django_timezone.now()
        update_fields.append("phone_verified_at")
    elif stored_phone is None and user.phone_verified_at is not None:
        user.phone_verified_at = None
        update_fields.append("phone_verified_at")

    if update_fields:
        user.save(update_fields=sorted(set(update_fields)))

    if assign_user_photo_from_storage_path(user, stored_path=profile_photo_path, overwrite=True):
        return
    if not remote_picture_url or user.photo:
        return

    cached_path, _cached_url = cache_remote_onboarding_picture(
        email=user.email,
        remote_url=remote_picture_url,
    )
    assign_user_photo_from_storage_path(user, stored_path=cached_path, overwrite=True)


def normalize_identity_names(
    email: str,
    first_name: str = "",
    last_name: str = "",
) -> tuple[str, str]:
    normalized_email = normalize_email(email)
    local_part = normalized_email.split("@", 1)[0] if normalized_email else ""
    tokens = [token for token in local_part.replace("_", ".").replace("-", ".").split(".") if token]

    normalized_first_name = (first_name or "").strip()
    normalized_last_name = (last_name or "").strip()

    if not normalized_first_name:
        fallback_first = tokens[0] if tokens else "utente"
        normalized_first_name = fallback_first[:1].upper() + fallback_first[1:]

    if not normalized_last_name:
        fallback_last = tokens[1] if len(tokens) > 1 else "Profilo"
        normalized_last_name = fallback_last[:1].upper() + fallback_last[1:]

    return normalized_first_name, normalized_last_name


def generate_unique_username(
    email: str,
    *,
    first_name: str = "",
    last_name: str = "",
) -> str:
    user_model = get_user_model()
    local_part = normalize_email(email).split("@", 1)[0] or "utente"
    base = slugify(f"{first_name}-{last_name}".strip("-")) or slugify(local_part) or "utente"
    base = base[:50] or "utente"
    candidate = base
    counter = 1

    while user_model.objects.filter(username__iexact=candidate).exists():
        suffix = f"-{counter}"
        candidate = f"{base[: max(1, 50 - len(suffix))]}{suffix}"
        counter += 1

    return candidate


def generate_access_code() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(6))


def generate_token_id() -> str:
    return secrets.token_urlsafe(24)


def get_request_metadata() -> tuple[str, str]:
    context = get_request_context()
    client_ip = str(context.get("client_ip", "") or "").strip()
    user_agent = str(context.get("user_agent", "") or "").strip()
    return client_ip, user_agent[:255]


def get_user_by_email(email: str):
    return get_user_model().objects.filter(email__iexact=normalize_email(email)).first()


def get_session_payload(session: AccessSession) -> dict:
    """Return a detached copy of the onboarding payload for safe in-memory mutations."""
    return dict(session.payload or {})


def save_session_payload(session: AccessSession, payload: dict) -> None:
    session.payload = payload
    session.save(update_fields=["payload", "updated_at"])


def consume_session(session: AccessSession, *, payload: dict | None = None) -> None:
    if payload is not None:
        session.payload = payload
    session.consumed_at = django_timezone.now()
    update_fields = ["consumed_at", "updated_at"]
    if payload is not None:
        update_fields.insert(0, "payload")
    session.save(update_fields=update_fields)


def get_onboarding_picture_sources(payload: dict) -> tuple[str, str]:
    """Extract the persisted and remote avatar references from an onboarding payload."""
    return (
        (payload.get("profile_photo_path") or "").strip(),
        (payload.get("picture_url") or payload.get("picture") or "").strip(),
    )


def merge_identity_payload(payload: dict, *, identity: dict) -> dict:
    return {
        **payload,
        "first_name": identity["first_name"],
        "last_name": identity["last_name"],
        "phone": identity["phone"],
        "language": identity["language"],
    }


def build_onboarding_identity(
    session: AccessSession,
    *,
    payload: dict | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    language: str | None = None,
    require_phone: bool = False,
    phone_error_message: str = "Il numero di telefono e obbligatorio.",
) -> dict:
    """Build the canonical identity snapshot used by onboarding and workspace flows."""
    session_payload = get_session_payload(session) if payload is None else dict(payload)
    normalized_first_name, normalized_last_name = normalize_identity_names(
        session.email,
        session_payload.get("first_name", "") if first_name is None else first_name,
        session_payload.get("last_name", "") if last_name is None else last_name,
    )
    normalized_phone = normalize_phone_number(
        session_payload.get("phone") if phone is None else phone,
    )
    normalized_language = normalize_language(
        session_payload.get("language") if language is None else language,
    )
    profile_photo_path, remote_picture_url = get_onboarding_picture_sources(session_payload)

    if require_phone and not normalized_phone:
        raise ValueError(phone_error_message)

    return {
        "first_name": normalized_first_name,
        "last_name": normalized_last_name,
        "phone": normalized_phone,
        "language": normalized_language,
        "profile_photo_path": profile_photo_path,
        "remote_picture_url": remote_picture_url,
    }


def user_has_active_workspaces(user) -> bool:
    return Profile.objects.filter(
        user=user,
        is_active=True,
        workspace__is_active=True,
    ).exists()


def revoke_auth_session(auth_session: AuthTokenSession, *, reason: str = "revoked") -> None:
    if auth_session.revoked_at is not None:
        return
    auth_session.revoked_at = django_timezone.now()
    auth_session.revoke_reason = reason[:64]
    auth_session.save(update_fields=["revoked_at", "revoke_reason", "updated_at"])


def revoke_user_auth_sessions(user, *, reason: str) -> int:
    sessions = list(
        AuthTokenSession.objects.filter(
            user=user,
            revoked_at__isnull=True,
        )
    )
    for session in sessions:
        revoke_auth_session(session, reason=reason)
    return len(sessions)


def build_auth_payload(
    user,
    *,
    issued_at: datetime | None = None,
    profile_id: int | None = None,
    auth_session: AuthTokenSession | None = None,
    orig_iat: int | None = None,
) -> dict:
    now = issued_at or datetime.now(timezone.utc)
    issued_at_ts = unix_timestamp(now)
    original_issued_at = orig_iat or issued_at_ts
    exp = issued_at_ts + settings.AUTH_ACCESS_TOKEN_TTL_SECONDS
    from edilcloud.modules.workspaces.services import build_user_auth_context

    auth_context = build_user_auth_context(user, profile_id=profile_id)
    client_ip, user_agent = get_request_metadata()
    session = auth_session or AuthTokenSession(user=user)
    access_jti = generate_token_id()
    refresh_jti = generate_token_id()
    session.current_access_jti = access_jti
    session.current_refresh_jti = refresh_jti
    session.current_profile_id = auth_context["extra"]["profile"]["id"] if auth_context.get("extra", {}).get("profile") else profile_id
    session.expires_at = now + timedelta(seconds=settings.AUTH_REFRESH_TOKEN_TTL_SECONDS)
    session.last_seen_at = now
    session.last_refreshed_at = now
    if client_ip:
        session.created_ip = session.created_ip or client_ip
        session.last_ip = client_ip
    if user_agent:
        session.user_agent = user_agent
    session.save()

    refresh_payload = {
        "sub": str(user.id),
        "sid": str(session.session_token),
        "rti": refresh_jti,
        "type": "refresh",
        "orig_iat": original_issued_at,
        "iat": issued_at_ts,
        "exp": issued_at_ts + settings.AUTH_REFRESH_TOKEN_TTL_SECONDS,
        "iss": settings.AUTH_TOKEN_ISSUER,
        "aud": settings.AUTH_REFRESH_TOKEN_AUDIENCE,
    }

    return {
        "sub": str(user.id),
        "sid": str(session.session_token),
        "jti": access_jti,
        "type": "access",
        "email": user.email,
        "username": user.username,
        "language": user.language,
        "active": user.is_active,
        "is_superuser": user.is_superuser,
        "is_staff": user.is_staff,
        "extra": auth_context["extra"],
        "main_profile": auth_context["main_profile"],
        "orig_iat": original_issued_at,
        "iat": issued_at_ts,
        "exp": exp,
        "iss": settings.AUTH_TOKEN_ISSUER,
        "aud": settings.AUTH_TOKEN_AUDIENCE,
        "_refresh_token": encode_refresh_token(refresh_payload),
        "_refresh_exp": refresh_payload["exp"],
        "_session_id": str(session.session_token),
    }


def encode_access_token(payload: dict) -> str:
    token_payload = {key: value for key, value in payload.items() if not str(key).startswith("_")}
    return jwt.encode(token_payload, settings.SECRET_KEY, algorithm="HS256")


def encode_refresh_token(payload: dict) -> str:
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_refresh_token(token: str, *, verify_exp: bool = True) -> dict:
    options = {"verify_exp": verify_exp}
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        audience=settings.AUTH_REFRESH_TOKEN_AUDIENCE,
        issuer=settings.AUTH_TOKEN_ISSUER,
        options=options,
    )


def validate_access_token_session(payload: dict) -> AuthTokenSession:
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Access token non valido.")

    session_id = payload.get("sid")
    access_jti = payload.get("jti")
    if not session_id or not access_jti:
        raise jwt.InvalidTokenError("Sessione non valida.")

    session = (
        AuthTokenSession.objects.select_related("user")
        .filter(session_token=session_id)
        .first()
    )
    if session is None or not session.is_active:
        raise jwt.InvalidTokenError(GENERIC_SESSION_ERROR)
    if session.current_access_jti != access_jti:
        raise jwt.InvalidTokenError(GENERIC_SESSION_ERROR)
    if str(session.user_id) != str(payload.get("sub")):
        raise jwt.InvalidTokenError(GENERIC_SESSION_ERROR)

    client_ip, _user_agent = get_request_metadata()
    updates: list[str] = []
    now = django_timezone.now()
    if session.last_seen_at is None or (now - session.last_seen_at).total_seconds() >= 15:
        session.last_seen_at = now
        updates.append("last_seen_at")
    if client_ip and session.last_ip != client_ip:
        session.last_ip = client_ip
        updates.append("last_ip")
    if updates:
        session.save(update_fields=[*updates, "updated_at"])
    return session


def decode_access_token(token: str, *, verify_exp: bool = True) -> dict:
    options = {"verify_exp": verify_exp}
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=["HS256"],
        audience=settings.AUTH_TOKEN_AUDIENCE,
        issuer=settings.AUTH_TOKEN_ISSUER,
        options=options,
    )
    validate_access_token_session(payload)
    return payload


def resolve_refresh_session(refresh_token: str, *, verify_exp: bool = True) -> tuple[AuthTokenSession, dict]:
    payload = decode_refresh_token(refresh_token, verify_exp=verify_exp)
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError(GENERIC_SESSION_ERROR)

    session_id = payload.get("sid")
    refresh_jti = payload.get("rti")
    session = (
        AuthTokenSession.objects.select_related("user")
        .filter(session_token=session_id)
        .first()
    )
    if session is None or not session.is_active:
        raise jwt.InvalidTokenError(GENERIC_SESSION_ERROR)
    if str(session.user_id) != str(payload.get("sub")):
        revoke_auth_session(session, reason="session_subject_mismatch")
        raise jwt.InvalidTokenError(GENERIC_SESSION_ERROR)
    if session.current_refresh_jti != refresh_jti:
        revoke_auth_session(session, reason="refresh_replay_detected")
        raise jwt.InvalidTokenError(GENERIC_SESSION_ERROR)
    return session, payload


def authenticated_response_from_payload(payload: dict) -> dict:
    return {
        "status": "authenticated",
        "token": encode_access_token(payload),
        "refresh_token": payload.get("_refresh_token"),
        "user": payload["email"],
        "active": payload["active"],
        "language": payload.get("language"),
        "is_superuser": bool(payload.get("is_superuser")),
        "is_staff": bool(payload.get("is_staff")),
        "extra": payload.get("extra"),
        "exp": payload["exp"],
        "orig_iat": payload["orig_iat"],
        "refresh_exp": payload.get("_refresh_exp"),
        "session_id": payload.get("_session_id"),
        "main_profile": payload.get("main_profile"),
    }


def issue_authenticated_response(
    user,
    *,
    profile_id: int | None = None,
    auth_session: AuthTokenSession | None = None,
    orig_iat: int | None = None,
) -> dict:
    return authenticated_response_from_payload(
        build_auth_payload(
            user,
            profile_id=profile_id,
            auth_session=auth_session,
            orig_iat=orig_iat,
        )
    )


def get_latest_access_session(email: str, provider: str) -> AccessSession | None:
    return (
        AccessSession.objects.filter(
            email__iexact=normalize_email(email),
            provider=provider,
            consumed_at__isnull=True,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def get_latest_password_reset_session(email: str) -> PasswordResetSession | None:
    return (
        PasswordResetSession.objects.filter(
            email__iexact=normalize_email(email),
            consumed_at__isnull=True,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def resolve_onboarding_session(onboarding_token: str) -> AccessSession:
    """Resolve an onboarding session token and reject expired or already consumed sessions."""
    session = (
        AccessSession.objects.filter(
            flow_token=onboarding_token,
            consumed_at__isnull=True,
            verified_at__isnull=False,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if session is None:
        raise ValueError("Sessione onboarding non valida.")
    if session.is_expired:
        raise ValueError("Sessione onboarding scaduta.")
    return session


def build_prefill(session: AccessSession, user=None) -> dict:
    payload = get_session_payload(session)

    existing_first_name = getattr(user, "first_name", "") if user else ""
    existing_last_name = getattr(user, "last_name", "") if user else ""
    existing_phone = getattr(user, "phone", "") if user else ""
    existing_language = getattr(user, "language", "it") if user else "it"
    existing_picture = file_field_url(getattr(user, "photo", None)) if user else ""
    _profile_photo_path, remote_picture_url = get_onboarding_picture_sources(payload)

    normalized_first_name, normalized_last_name = normalize_identity_names(
        session.email,
        payload.get("first_name") or existing_first_name,
        payload.get("last_name") or existing_last_name,
    )

    return {
        "email": session.email,
        "first_name": normalized_first_name,
        "last_name": normalized_last_name,
        "phone": (payload.get("phone") or existing_phone or "").strip(),
        "language": normalize_language(payload.get("language") or existing_language),
        "picture": remote_picture_url or storage_public_url(payload.get("profile_photo_path")) or existing_picture,
        "company_name": "",
        "company_email": "",
        "company_phone": "",
        "company_website": "",
        "company_vat_number": "",
        "company_description": "",
        "company_logo": None,
    }


def build_onboarding_response(session: AccessSession, user=None) -> dict:
    return {
        "status": "onboarding_required",
        "onboarding_token": str(session.flow_token),
        "prefill": build_prefill(session, user=user),
    }


def sync_session_picture_to_existing_profile(session: AccessSession, user) -> None:
    payload = get_session_payload(session)
    profile_photo_path, remote_picture_url = get_onboarding_picture_sources(payload)
    sync_user_main_identity(
        user,
        first_name=payload.get("first_name", ""),
        last_name=payload.get("last_name", ""),
        phone=payload.get("phone", ""),
        language=payload.get("language", user.language),
        profile_photo_path=profile_photo_path,
        remote_picture_url=remote_picture_url,
        mark_phone_verified=bool(payload.get("phone")),
    )

    from edilcloud.modules.workspaces.services import attach_profile_photo, select_default_profile

    profile = select_default_profile(user)
    if profile is None:
        return

    attach_profile_photo(
        profile,
        temp_photo_path=profile_photo_path,
        remote_picture_url=remote_picture_url,
        overwrite=False,
    )


def build_post_identity_response(session: AccessSession, user=None) -> dict:
    """Return an authenticated response when the user already belongs to a workspace."""
    if user is not None:
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])
        if user_has_active_workspaces(user):
            sync_session_picture_to_existing_profile(session, user)
            consume_session(session)
            return issue_authenticated_response(user)
    return build_onboarding_response(session, user=user)


def get_onboarding_session_state(*, onboarding_token: str) -> dict:
    session = resolve_onboarding_session(onboarding_token)
    user = get_user_by_email(session.email)
    return build_onboarding_response(session, user=user)


def send_access_code_email(email: str, code: str) -> None:
    """Send the transactional email used for passwordless access-code sign in."""
    ttl_minutes = max(1, settings.AUTH_ACCESS_CODE_TTL_SECONDS // 60)
    context = {
        "code": code,
        "ttl_minutes": ttl_minutes,
        "support_email": settings.DEFAULT_FROM_EMAIL,
    }
    subject = render_to_string(
        "identity/emails/access_code_subject.txt",
        context,
    ).strip()
    text_body = render_to_string("identity/emails/access_code.txt", context)
    html_body = render_to_string("identity/emails/access_code.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.REGISTRATION_FROM_EMAIL or settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    message.attach_alternative(html_body, "text/html")
    send_email_message(message)


def send_password_reset_email(email: str, code: str) -> None:
    ttl_minutes = max(1, settings.AUTH_PASSWORD_RESET_TTL_SECONDS // 60)
    context = {
        "code": code,
        "ttl_minutes": ttl_minutes,
        "support_email": settings.DEFAULT_FROM_EMAIL,
    }
    subject = render_to_string(
        "identity/emails/password_reset_subject.txt",
        context,
    ).strip()
    text_body = render_to_string("identity/emails/password_reset.txt", context)
    html_body = render_to_string("identity/emails/password_reset.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.REGISTRATION_FROM_EMAIL or settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    message.attach_alternative(html_body, "text/html")
    send_email_message(message)


def login_user(*, username_or_email: str, password: str) -> dict:
    user_model = get_user_model()
    candidate = (
        user_model.objects.filter(email__iexact=username_or_email).first()
        or user_model.objects.filter(username__iexact=username_or_email).first()
    )
    if candidate is None:
        increment_counter("auth.login.failed", reason="unknown_user")
        raise ValueError(GENERIC_LOGIN_ERROR)

    user = authenticate(username=candidate.email, password=password)
    if user is None:
        increment_counter("auth.login.failed", reason="invalid_password")
        raise ValueError(GENERIC_LOGIN_ERROR)
    if not user.is_active:
        increment_counter("auth.login.failed", reason="inactive_user")
        raise ValueError(GENERIC_LOGIN_ERROR)

    increment_counter("auth.login.succeeded")
    logger.info("auth.login.succeeded", extra={"event": "auth.login.succeeded", "user_id": user.id})
    return issue_authenticated_response(user)


def verify_user_token(token: str) -> dict:
    return decode_access_token(token)


def refresh_user_token(refresh_token: str, profile_id: int | None = None) -> dict:
    auth_session, payload = resolve_refresh_session(refresh_token)
    user = auth_session.user
    if not user.is_active:
        revoke_auth_session(auth_session, reason="inactive_user")
        raise ValueError(GENERIC_SESSION_ERROR)

    increment_counter("auth.refresh.succeeded")
    logger.info(
        "auth.refresh.succeeded",
        extra={
            "event": "auth.refresh.succeeded",
            "user_id": user.id,
            "session_id": str(auth_session.session_token),
        },
    )
    return issue_authenticated_response(
        user,
        profile_id=profile_id or auth_session.current_profile_id,
        auth_session=auth_session,
        orig_iat=payload.get("orig_iat"),
    )


def logout_user(*, refresh_token: str) -> dict:
    try:
        auth_session, _payload = resolve_refresh_session(refresh_token, verify_exp=False)
    except jwt.InvalidTokenError:
        return {
            "status": "ok",
            "detail": "Logout eseguito.",
        }

    revoke_auth_session(auth_session, reason="logout")
    increment_counter("auth.logout.succeeded")
    logger.info(
        "auth.logout.succeeded",
        extra={
            "event": "auth.logout.succeeded",
            "user_id": auth_session.user_id,
            "session_id": str(auth_session.session_token),
        },
    )
    return {
        "status": "ok",
        "detail": "Logout eseguito.",
    }


@transaction.atomic
def register_user(
    *,
    email: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
    username: str | None = None,
    language: str = "it",
):
    user_model = get_user_model()
    normalized_email = normalize_email(email)

    if user_model.objects.filter(email__iexact=normalized_email).exists():
        raise ValueError("Esiste gia un utente con questa email.")

    if username and user_model.objects.filter(username__iexact=username).exists():
        raise ValueError("Esiste gia un utente con questo username.")

    try:
        validate_password(password)
    except Exception as exc:
        messages = getattr(exc, "messages", None) or ["Password non valida."]
        raise ValueError(" ".join(messages)) from exc

    normalized_username = username or normalized_email.split("@", 1)[0]
    user = user_model.objects.create_user(
        email=normalized_email,
        password=password,
        username=normalized_username,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        language=normalize_language(language),
    )
    return user


@transaction.atomic
def request_access_code(*, email: str) -> dict:
    """Create a short-lived access code while enforcing resend cooldown limits."""
    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValueError("Email obbligatoria.")

    latest_session = get_latest_access_session(normalized_email, AuthProvider.EMAIL)
    cooldown_seconds = settings.AUTH_ACCESS_CODE_RESEND_COOLDOWN_SECONDS
    if latest_session and not latest_session.verified_at and not latest_session.is_expired:
        elapsed = (django_timezone.now() - latest_session.created_at).total_seconds()
        if elapsed < cooldown_seconds:
            wait_seconds = max(1, int(cooldown_seconds - elapsed))
            raise ValueError(f"Attendi {wait_seconds} secondi prima di richiedere un nuovo codice.")

    code = generate_access_code()
    session = AccessSession.objects.create(
        email=normalized_email,
        provider=AuthProvider.EMAIL,
        code_hash=make_password(code),
        expires_at=django_timezone.now() + timedelta(seconds=settings.AUTH_ACCESS_CODE_TTL_SECONDS),
    )
    send_access_code_email(normalized_email, code)

    response = {
        "detail": "Ti abbiamo inviato un codice di accesso via email.",
        "status": "code_sent",
    }
    if settings.DEBUG and settings.AUTH_INCLUDE_DEBUG_CODES:
        response["dev_code"] = code
        response["debug_flow_token"] = str(session.flow_token)
    increment_counter("auth.access_code.requested")
    return response


@transaction.atomic
def confirm_access_code(*, email: str, code: str) -> dict:
    """Validate an emailed access code and transition the user into auth or onboarding."""
    normalized_email = normalize_email(email)
    normalized_code = (code or "").strip()
    session = get_latest_access_session(normalized_email, AuthProvider.EMAIL)

    if session is None:
        raise ValueError("Nessun codice attivo trovato per questa email.")
    if session.is_expired:
        raise ValueError("Il codice e scaduto. Richiedine uno nuovo.")
    if session.failed_attempts >= settings.AUTH_ACCESS_CODE_MAX_ATTEMPTS:
        raise ValueError("Hai superato il numero massimo di tentativi. Richiedi un nuovo codice.")
    if not check_password(normalized_code, session.code_hash):
        session.failed_attempts += 1
        if session.failed_attempts >= settings.AUTH_ACCESS_CODE_MAX_ATTEMPTS:
            session.consumed_at = django_timezone.now()
            session.save(update_fields=["failed_attempts", "consumed_at", "updated_at"])
        else:
            session.save(update_fields=["failed_attempts", "updated_at"])
        raise ValueError("Il codice non e valido.")

    session.verified_at = django_timezone.now()
    session.expires_at = django_timezone.now() + timedelta(seconds=settings.AUTH_ONBOARDING_SESSION_TTL_SECONDS)
    session.failed_attempts = 0
    session.save(update_fields=["verified_at", "expires_at", "failed_attempts", "updated_at"])

    user = get_user_by_email(normalized_email)
    increment_counter("auth.access_code.confirmed")
    return build_post_identity_response(session, user=user)


@transaction.atomic
def request_password_reset(*, email: str) -> dict:
    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValueError("Email obbligatoria.")

    user = get_user_by_email(normalized_email)
    if user is None or not user.is_active or not user.has_usable_password():
        increment_counter("auth.password_reset.requested", outcome="anonymous")
        return {
            "status": "ok",
            "detail": GENERIC_PASSWORD_RESET_REQUEST_DETAIL,
        }

    latest_session = get_latest_password_reset_session(normalized_email)
    cooldown_seconds = settings.AUTH_PASSWORD_RESET_RESEND_COOLDOWN_SECONDS
    if latest_session and latest_session.is_active:
        elapsed = (django_timezone.now() - latest_session.created_at).total_seconds()
        if elapsed < cooldown_seconds:
            return {
                "status": "ok",
                "detail": GENERIC_PASSWORD_RESET_REQUEST_DETAIL,
            }

    code = generate_access_code()
    PasswordResetSession.objects.create(
        user=user,
        email=normalized_email,
        code_hash=make_password(code),
        expires_at=django_timezone.now() + timedelta(seconds=settings.AUTH_PASSWORD_RESET_TTL_SECONDS),
        requested_ip=get_request_metadata()[0] or None,
    )
    send_password_reset_email(normalized_email, code)
    increment_counter("auth.password_reset.requested", outcome="sent")
    logger.info(
        "auth.password_reset.requested",
        extra={"event": "auth.password_reset.requested", "user_id": user.id},
    )
    return {
        "status": "ok",
        "detail": GENERIC_PASSWORD_RESET_REQUEST_DETAIL,
    }


@transaction.atomic
def confirm_password_reset(*, email: str, code: str, new_password: str) -> dict:
    normalized_email = normalize_email(email)
    normalized_code = (code or "").strip()
    session = get_latest_password_reset_session(normalized_email)

    if session is None or session.is_expired:
        increment_counter("auth.password_reset.failed", reason="missing_or_expired")
        raise ValueError(GENERIC_PASSWORD_RESET_CONFIRM_ERROR)
    if session.failed_attempts >= settings.AUTH_PASSWORD_RESET_MAX_ATTEMPTS:
        increment_counter("auth.password_reset.failed", reason="too_many_attempts")
        raise ValueError(GENERIC_PASSWORD_RESET_CONFIRM_ERROR)
    if not check_password(normalized_code, session.code_hash):
        session.failed_attempts += 1
        if session.failed_attempts >= settings.AUTH_PASSWORD_RESET_MAX_ATTEMPTS:
            session.consumed_at = django_timezone.now()
            session.save(update_fields=["failed_attempts", "consumed_at", "updated_at"])
        else:
            session.save(update_fields=["failed_attempts", "updated_at"])
        increment_counter("auth.password_reset.failed", reason="invalid_code")
        raise ValueError(GENERIC_PASSWORD_RESET_CONFIRM_ERROR)

    user = session.user
    try:
        validate_password(new_password, user=user)
    except Exception as exc:
        messages = getattr(exc, "messages", None) or ["Password non valida."]
        raise ValueError(" ".join(messages)) from exc

    user.set_password(new_password)
    user.save(update_fields=["password"])
    session.consumed_at = django_timezone.now()
    session.save(update_fields=["consumed_at", "updated_at"])
    revoked_count = revoke_user_auth_sessions(user, reason="password_reset")
    increment_counter("auth.password_reset.succeeded")
    logger.info(
        "auth.password_reset.succeeded",
        extra={
            "event": "auth.password_reset.succeeded",
            "user_id": user.id,
            "revoked_sessions": revoked_count,
        },
    )
    return {
        "status": "ok",
        "detail": "Password aggiornata con successo.",
    }


def verify_google_credential(credential: str) -> dict:
    normalized_credential = (credential or "").strip()
    if not normalized_credential:
        raise ValueError("Credential Google mancante.")
    if not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise ValueError("Google client id non configurato.")

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except ImportError as exc:
        raise ValueError(
            "Dipendenze Google non installate correttamente. Servono google-auth e requests."
        ) from exc

    id_info = google_id_token.verify_oauth2_token(
        normalized_credential,
        google_requests.Request(),
        settings.GOOGLE_OAUTH_CLIENT_ID,
    )
    if id_info.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise ValueError("Issuer Google non valido.")
    if not id_info.get("email_verified"):
        raise ValueError("L'email Google non risulta verificata.")
    return id_info


def verify_google_access_token(access_token: str) -> dict:
    normalized_access_token = (access_token or "").strip()
    if not normalized_access_token:
        raise ValueError("Token Google mancante.")

    request = Request(
        GOOGLE_USERINFO_ENDPOINT,
        headers={
            "Authorization": f"Bearer {normalized_access_token}",
            "Accept": "application/json",
        },
    )

    try:
        with urlopen(request, timeout=5) as response:
            raw_payload = response.read()
    except Exception as exc:
        raise ValueError("Token Google non valido.") from exc

    try:
        id_info = json.loads(raw_payload.decode("utf-8") or "{}")
    except Exception as exc:
        raise ValueError("Risposta Google non valida.") from exc

    if not normalize_email(id_info.get("email")):
        raise ValueError("Email Google non disponibile.")

    email_verified = id_info.get("email_verified")
    if isinstance(email_verified, str):
        email_verified = email_verified.strip().lower() == "true"
    if not email_verified:
        raise ValueError("L'email Google non risulta verificata.")

    return id_info


def authenticate_with_google_identity(*, id_info: dict) -> dict:
    """Create or resume the onboarding flow from normalized Google identity claims."""
    if not isinstance(id_info, dict):
        raise ValueError("Identita Google non valida.")

    email = normalize_email(id_info.get("email"))
    if not email:
        raise ValueError("Email Google non disponibile.")

    remote_picture_url = (id_info.get("picture") or "").strip()
    cached_picture_path, cached_picture_url = cache_remote_onboarding_picture(
        email=email,
        remote_url=remote_picture_url,
    )

    session = AccessSession.objects.create(
        email=email,
        provider=AuthProvider.GOOGLE,
        expires_at=django_timezone.now() + timedelta(seconds=settings.AUTH_ONBOARDING_SESSION_TTL_SECONDS),
        verified_at=django_timezone.now(),
        payload={
            "first_name": (id_info.get("given_name") or "").strip(),
            "last_name": (id_info.get("family_name") or "").strip(),
            "picture": cached_picture_url or remote_picture_url,
            "picture_url": remote_picture_url,
            "profile_photo_path": cached_picture_path,
            "language": normalize_language(id_info.get("locale")),
            "google_sub": (id_info.get("sub") or "").strip(),
        },
    )
    user = get_user_by_email(email)
    return build_post_identity_response(session, user=user)


@transaction.atomic
def authenticate_with_google(*, credential: str = "", access_token: str = "") -> dict:
    """Authenticate with a Google ID token or OAuth access token and bootstrap onboarding."""
    normalized_credential = (credential or "").strip()
    normalized_access_token = (access_token or "").strip()

    if normalized_credential:
        return authenticate_with_google_identity(
            id_info=verify_google_credential(normalized_credential),
        )
    if normalized_access_token:
        return authenticate_with_google_identity(
            id_info=verify_google_access_token(normalized_access_token),
        )

    raise ValueError("Credential Google mancante.")


@transaction.atomic
def update_onboarding_profile(
    *,
    onboarding_token: str,
    first_name: str,
    last_name: str,
    phone: str,
    language: str = "it",
    photo=None,
) -> dict:
    """Persist the profile details collected before workspace selection."""
    session = resolve_onboarding_session(onboarding_token)
    payload = get_session_payload(session)
    identity = build_onboarding_identity(
        session,
        payload=payload,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        language=language,
        require_phone=True,
    )
    payload = merge_identity_payload(payload, identity=identity)
    if photo is not None:
        previous_path = (payload.get("profile_photo_path") or "").strip()
        stored_path, stored_url = store_onboarding_profile_photo(email=session.email, uploaded_file=photo)
        delete_storage_path(previous_path)
        payload["profile_photo_path"] = stored_path
        payload["picture"] = stored_url
        payload["picture_url"] = ""

    save_session_payload(session, payload)

    user = get_or_create_onboarding_user(session, identity=identity)
    return build_onboarding_response(session, user=user)


def get_or_create_onboarding_user(
    session: AccessSession,
    *,
    identity: dict | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    language: str | None = None,
):
    """Ensure the onboarding email is backed by an active user record with normalized identity data."""
    user_model = get_user_model()
    resolved_identity = identity or build_onboarding_identity(
        session,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        language=language,
    )
    normalized_first_name = resolved_identity["first_name"]
    normalized_last_name = resolved_identity["last_name"]
    normalized_language = resolved_identity["language"]
    normalized_phone = resolved_identity["phone"]
    normalized_phone_for_storage = normalize_phone_storage_value(normalized_phone)

    user = user_model.objects.filter(email__iexact=session.email).first()
    if user is None:
        if normalized_phone_for_storage:
            ensure_unique_main_phone(normalized_phone_for_storage)
        user = user_model.objects.create_user(
            email=session.email,
            password=None,
            username=generate_unique_username(
                session.email,
                first_name=normalized_first_name,
                last_name=normalized_last_name,
            ),
            first_name=normalized_first_name,
            last_name=normalized_last_name,
            language=normalized_language,
            phone=normalized_phone_for_storage,
            phone_verified_at=django_timezone.now() if normalized_phone_for_storage else None,
            is_active=True,
        )
    else:
        sync_user_main_identity(
            user,
            first_name=normalized_first_name,
            last_name=normalized_last_name,
            phone=normalized_phone,
            language=normalized_language,
            profile_photo_path=resolved_identity["profile_photo_path"],
            remote_picture_url=resolved_identity["remote_picture_url"],
            mark_phone_verified=bool(normalized_phone),
        )
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])

    sync_user_main_identity(
        user,
        first_name=normalized_first_name,
        last_name=normalized_last_name,
        phone=normalized_phone,
        language=normalized_language,
        profile_photo_path=resolved_identity["profile_photo_path"],
        remote_picture_url=resolved_identity["remote_picture_url"],
        mark_phone_verified=bool(normalized_phone),
    )

    payload = merge_identity_payload(get_session_payload(session), identity=resolved_identity)
    save_session_payload(session, payload)

    return user


def get_or_create_onboarding_actor(
    session: AccessSession,
    *,
    payload: dict | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    language: str | None = None,
    require_phone: bool = False,
    phone_error_message: str = "Il numero di telefono e obbligatorio.",
):
    payload = get_session_payload(session) if payload is None else dict(payload)
    identity = build_onboarding_identity(
        session,
        payload=payload,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        language=language,
        require_phone=require_phone,
        phone_error_message=phone_error_message,
    )
    user = get_or_create_onboarding_user(session, identity=identity)
    return user, payload, identity


@transaction.atomic
def complete_onboarding(
    *,
    onboarding_token: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    language: str = "it",
    company_name: str,
    company_email: str = "",
    company_phone: str = "",
    company_website: str = "",
    company_vat_number: str = "",
    company_description: str = "",
    workspace_type: str = "",
    position: str = "",
    company_logo=None,
) -> dict:
    """Finalize onboarding either by creating the first workspace or authenticating an existing member."""
    session = resolve_onboarding_session(onboarding_token)
    user, payload, identity = get_or_create_onboarding_actor(
        session,
        first_name=first_name or None,
        last_name=last_name or None,
        phone=phone or None,
        language=language or None,
        require_phone=True,
    )

    if user_has_active_workspaces(user):
        consume_session(session, payload=merge_identity_payload(payload, identity=identity))
        response = issue_authenticated_response(user)
        response["onboarding_completed"] = True
        return response

    from edilcloud.modules.workspaces.services import create_workspace_for_user

    result = create_workspace_for_user(
        user,
        company_name=(company_name or "").strip(),
        company_email=(company_email or session.email).strip(),
        company_phone=(company_phone or "").strip(),
        company_website=(company_website or "").strip(),
        company_vat_number=(company_vat_number or "").strip(),
        company_description=(company_description or "").strip(),
        company_logo=company_logo,
        workspace_type=(workspace_type or "").strip(),
        first_name=identity["first_name"],
        last_name=identity["last_name"],
        phone=identity["phone"],
        language=identity["language"],
        position=(position or "").strip(),
        profile_photo_path=identity["profile_photo_path"],
        remote_picture_url=identity["remote_picture_url"],
    )

    consume_session(session, payload=merge_identity_payload(payload, identity=identity))

    auth = result["auth"]
    auth["onboarding_completed"] = True
    return auth


def serialize_onboarding_invite(invite) -> dict:
    return {
        "id": invite.id,
        "invite_code": invite.invite_code,
        "uidb36": invite.uidb36,
        "token": invite.token,
        "email": invite.email,
        "role": invite.role,
        "status": 0,
        "company": {
            "id": invite.workspace_id,
            "name": invite.workspace.name,
            "slug": invite.workspace.slug,
        },
    }


def list_onboarding_workspace_invites(*, onboarding_token: str) -> list[dict]:
    session = resolve_onboarding_session(onboarding_token)
    from edilcloud.modules.workspaces.models import WorkspaceInvite

    invites = (
        WorkspaceInvite.objects.select_related("workspace")
        .filter(
            email__iexact=session.email,
            accepted_at__isnull=True,
        )
        .order_by("-created_at", "-id")
    )

    now = django_timezone.now()
    return [
        serialize_onboarding_invite(invite)
        for invite in invites
        if invite.expires_at is None or invite.expires_at >= now
    ]


@transaction.atomic
def accept_onboarding_workspace_invite(
    *,
    onboarding_token: str,
    uidb36: str,
    token: str,
) -> dict:
    """Join a workspace directly from an invite link during onboarding."""
    session = resolve_onboarding_session(onboarding_token)
    user, _payload, identity = get_or_create_onboarding_actor(
        session,
        require_phone=True,
        phone_error_message=(
            "Completa prima il main profile con un numero di telefono "
            "prima di entrare nel workspace invitato."
        ),
    )

    from edilcloud.modules.workspaces.services import accept_workspace_invite

    result = accept_workspace_invite(
        user,
        uidb36=uidb36,
        token=token,
        first_name=identity["first_name"],
        last_name=identity["last_name"],
        phone=identity["phone"],
        language=identity["language"],
        temp_photo_path=identity["profile_photo_path"],
        remote_picture_url=identity["remote_picture_url"],
    )
    consume_session(session)

    auth = result["auth"]
    auth["joined_workspace"] = True
    auth["onboarding_completed"] = True
    return auth


@transaction.atomic
def accept_onboarding_workspace_invite_by_code(
    *,
    onboarding_token: str,
    invite_code: str,
) -> dict:
    """Join a workspace by using the invite code shared in the transactional email."""
    session = resolve_onboarding_session(onboarding_token)
    user, _payload, identity = get_or_create_onboarding_actor(
        session,
        require_phone=True,
        phone_error_message=(
            "Completa prima il main profile con un numero di telefono "
            "prima di entrare nel workspace invitato."
        ),
    )

    from edilcloud.modules.workspaces.services import accept_workspace_invite_by_code

    result = accept_workspace_invite_by_code(
        user,
        invite_code=invite_code,
        first_name=identity["first_name"],
        last_name=identity["last_name"],
        phone=identity["phone"],
        language=identity["language"],
        temp_photo_path=identity["profile_photo_path"],
        remote_picture_url=identity["remote_picture_url"],
    )

    consume_session(session)

    auth = result["auth"]
    auth["joined_workspace"] = True
    auth["onboarding_completed"] = True
    return auth


def search_onboarding_workspaces(*, onboarding_token: str, query: str) -> list[dict]:
    session = resolve_onboarding_session(onboarding_token)
    from edilcloud.modules.workspaces.services import get_workspace_search_results

    return get_workspace_search_results(email=session.email, query=query)


@transaction.atomic
def request_onboarding_workspace_access(
    *,
    onboarding_token: str,
    workspace_id: int,
    position: str = "",
    message: str = "",
) -> dict:
    """Create a moderated access request for an existing workspace during onboarding."""
    session = resolve_onboarding_session(onboarding_token)
    user, _payload, identity = get_or_create_onboarding_actor(
        session,
        require_phone=True,
        phone_error_message="Completa prima il profilo con un numero di telefono valido.",
    )

    from edilcloud.modules.workspaces.services import create_workspace_access_request

    return create_workspace_access_request(
        user,
        workspace_id=workspace_id,
        email=session.email,
        first_name=identity["first_name"],
        last_name=identity["last_name"],
        phone=identity["phone"],
        language=identity["language"],
        position=(position or "").strip(),
        message=(message or "").strip(),
        photo_path=identity["profile_photo_path"],
        picture_url=identity["remote_picture_url"],
    )
