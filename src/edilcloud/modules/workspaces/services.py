"""Workspace services used by the authenticated and onboarding flows."""

import mimetypes
import re
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from edilcloud.modules.files.media_optimizer import optimize_media_content, optimize_media_for_storage
from edilcloud.modules.workspaces.emails import (
    send_workspace_access_approved_email,
    send_workspace_access_request_review_email,
    send_workspace_invite_email,
)
from edilcloud.modules.workspaces.models import (
    AccessRequestStatus,
    Profile,
    Workspace,
    WorkspaceAccessRequest,
    WorkspaceInvite,
    WorkspaceRole,
    generate_token,
    generate_uidb36,
)


ROLE_PRIORITY = {
    WorkspaceRole.OWNER: 4,
    WorkspaceRole.DELEGATE: 3,
    WorkspaceRole.MANAGER: 2,
    WorkspaceRole.WORKER: 1,
}

MANAGEABLE_ROLES = {WorkspaceRole.OWNER, WorkspaceRole.DELEGATE}


def get_role_priority(role: str | None) -> int:
    return ROLE_PRIORITY.get(role, 0)


def file_url(file_field) -> str | None:
    if not file_field:
        return None
    try:
        return file_field.url
    except ValueError:
        return None


def storage_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return default_storage.url(path)
    except Exception:
        return None


def normalize_role(role: str | None, *, default: str = WorkspaceRole.WORKER) -> str:
    if not role:
        return default
    normalized = role.strip().lower()
    if normalized in {WorkspaceRole.OWNER, "owner"}:
        return WorkspaceRole.OWNER
    if normalized in {WorkspaceRole.DELEGATE, "delegate"}:
        return WorkspaceRole.DELEGATE
    if normalized in {WorkspaceRole.MANAGER, "manager"}:
        return WorkspaceRole.MANAGER
    if normalized in {WorkspaceRole.WORKER, "worker"}:
        return WorkspaceRole.WORKER
    return default


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def tokenize_workspace_query(query: str | None) -> list[str]:
    return [
        token
        for token in re.split(r"[^\w]+", (query or "").strip().lower())
        if token
    ]


def build_workspace_search_filter(query: str | None) -> Q:
    tokens = tokenize_workspace_query(query)
    if not tokens:
        return Q()

    query_filter = Q()
    for token in tokens:
        token_filter = (
            Q(name__icontains=token)
            | Q(slug__icontains=token)
            | Q(email__icontains=token)
            | Q(vat_number__icontains=token)
        )
        query_filter &= token_filter
    return query_filter


def normalize_invite_code(invite_code: str | None) -> str:
    digits = "".join(character for character in (invite_code or "") if character.isdigit())
    if len(digits) != 8:
        return ""
    return f"{digits[:4]}-{digits[4:]}"


def select_default_profile(user) -> Profile | None:
    profiles = list(
        Profile.objects.select_related("workspace")
        .filter(user=user, is_active=True, workspace__is_active=True)
        .order_by("id")
    )
    if not profiles:
        return None
    return sorted(profiles, key=lambda profile: (-get_role_priority(profile.role), profile.id))[0]


def get_user_profile(user, profile_id: int) -> Profile | None:
    return (
        Profile.objects.select_related("workspace")
        .filter(
            id=profile_id,
            user=user,
            is_active=True,
            workspace__is_active=True,
        )
        .first()
    )


def build_user_auth_context(user, *, profile_id: int | None = None) -> dict:
    selected_profile = None
    if profile_id is not None:
        selected_profile = get_user_profile(user, profile_id)
        if selected_profile is None:
            if profile_id == user.id:
                return {
                    "extra": {
                        "profile": {
                            "id": user.id,
                            "role": WorkspaceRole.OWNER,
                            "company": None,
                        }
                    },
                    "main_profile": user.id,
                }
            raise ValueError("Profilo non valido.")
    else:
        selected_profile = select_default_profile(user)

    if selected_profile is None:
        return {
            "extra": {
                "profile": {
                    "id": user.id,
                    "role": WorkspaceRole.OWNER,
                    "company": None,
                }
            },
            "main_profile": user.id,
        }

    return {
        "extra": {
            "profile": {
                "id": selected_profile.id,
                "role": selected_profile.role,
                "company": selected_profile.workspace_id,
            }
        },
        "main_profile": selected_profile.id,
    }


def serialize_workspace(workspace: Workspace) -> dict:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug,
        "logo": file_url(workspace.logo),
        "workspace_type": workspace.workspace_type or None,
        "email": workspace.email or None,
        "phone": workspace.phone or None,
        "website": workspace.website or None,
        "vat_number": workspace.vat_number or None,
        "description": workspace.description or None,
        "color": workspace.color or None,
    }


def profile_photo_url(profile: Profile) -> str | None:
    return file_url(profile.photo) or file_url(getattr(profile.user, "photo", None))


def serialize_profile(profile: Profile) -> dict:
    return {
        "id": profile.id,
        "role": profile.role,
        "position": profile.position or None,
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "email": profile.email,
        "phone": profile.phone or None,
        "phone_verified_at": profile.phone_verified_at,
        "language": profile.language or None,
        "photo": profile_photo_url(profile),
        "company": serialize_workspace(profile.workspace),
    }


def serialize_workspace_option(profile: Profile) -> dict:
    workspace = profile.workspace
    return {
        "profileId": profile.id,
        "companyId": workspace.id,
        "companyName": workspace.name,
        "companySlug": workspace.slug,
        "companyLogo": file_url(workspace.logo),
        "role": profile.role,
        "memberName": profile.member_name,
        "photo": profile_photo_url(profile),
    }


def serialize_company_record(workspace: Workspace) -> dict:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "slug": workspace.slug or None,
        "url": workspace.website or None,
        "email": workspace.email or None,
        "phone": workspace.phone or None,
        "logo": file_url(workspace.logo),
        "address": None,
        "province": None,
        "cap": None,
        "country": None,
        "tax_code": workspace.vat_number or None,
        "vat_number": workspace.vat_number or None,
        "pec": None,
        "billing_email": None,
    }


def list_workspace_options(user) -> list[dict]:
    profiles = (
        Profile.objects.select_related("workspace")
        .filter(user=user, is_active=True, workspace__is_active=True)
        .order_by("workspace__name", "id")
    )
    return [serialize_workspace_option(profile) for profile in profiles]


def list_active_profiles(user) -> list[dict]:
    profiles = (
        Profile.objects.select_related("workspace")
        .filter(user=user, is_active=True, workspace__is_active=True)
        .order_by("workspace__name", "id")
    )
    return [serialize_profile(profile) for profile in profiles]


def resolve_claimed_profile_id(*, claims: dict | None = None) -> int | None:
    raw_value = (claims or {}).get("main_profile")
    if raw_value in {None, ""}:
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def resolve_active_workspace_profile(user, *, profile_id: int | None = None) -> Profile:
    if profile_id is not None:
        profile = get_user_profile(user, profile_id)
        if profile is not None:
            return profile

    profile = select_default_profile(user)
    if profile is None:
        raise ValueError("Nessun profilo workspace attivo disponibile.")
    return profile


def serialize_current_workspace_profile(profile: Profile) -> dict:
    return {
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "email": profile.email,
        "phone": profile.phone or None,
        "language": profile.language or None,
        "position": profile.position or None,
        "photo": profile_photo_url(profile),
        "company": serialize_workspace(profile.workspace) if profile.workspace_id else None,
        "company_name": profile.workspace.name if profile.workspace_id else None,
    }


def get_current_workspace_profile_settings(user, *, claims: dict | None = None) -> dict:
    profile = resolve_active_workspace_profile(
        user,
        profile_id=resolve_claimed_profile_id(claims=claims),
    )
    hydrate_profile_from_main_profile(profile, user=user, overwrite_missing_only=True)
    return serialize_current_workspace_profile(profile)


def serialize_workspace_team_member(profile: Profile) -> dict:
    return {
        "id": encode_workspace_team_member_id(profile=profile),
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "email": profile.email,
        "phone": profile.phone or None,
        "mobile": None,
        "language": profile.language or None,
        "position": profile.position or None,
        "role": profile.role,
        "photo": profile_photo_url(profile),
        "company_invitation_date": profile.created_at,
        "profile_invitation_date": profile.created_at,
        "invitation_refuse_date": None,
        "can_access_files": True,
        "can_access_chat": True,
        "user": (
            {
                "id": profile.user_id,
                "first_name": profile.user.first_name or None,
                "last_name": profile.user.last_name or None,
            }
            if profile.user_id and profile.user
            else None
        ),
    }


def list_current_workspace_members(user, *, profile_id: int | None = None) -> dict:
    active_profile = resolve_active_workspace_profile(user, profile_id=profile_id)
    profiles = list(
        Profile.objects.select_related("user")
        .filter(workspace=active_profile.workspace)
        .order_by("first_name", "last_name", "id")
    )
    invites = list(
        WorkspaceInvite.objects.select_related("workspace")
        .filter(
            workspace=active_profile.workspace,
            accepted_at__isnull=True,
        )
        .order_by("-created_at", "-id")
    )

    approved = [serialize_workspace_team_member(profile) for profile in profiles if profile.is_active]
    disabled = [serialize_workspace_team_member(profile) for profile in profiles if not profile.is_active]
    waiting = [
        serialize_workspace_invite_member(invite)
        for invite in invites
        if is_workspace_invite_active(invite) and invite.refused_at is None
    ]
    refused = [
        serialize_workspace_invite_member(invite)
        for invite in invites
        if is_workspace_invite_active(invite) and invite.refused_at is not None
    ]
    return {
        "approved": approved,
        "waiting": waiting,
        "refused": refused,
        "disabled": disabled,
    }


def search_companies(*, query: str, limit: int = 12) -> list[dict]:
    normalized_query = (query or "").strip()
    workspaces = Workspace.objects.filter(is_active=True)
    if normalized_query:
        workspaces = workspaces.filter(build_workspace_search_filter(normalized_query))

    return [
        serialize_company_record(workspace)
        for workspace in workspaces.order_by("name", "id")[:limit]
    ]


def serialize_company_contact(profile: Profile) -> dict:
    return {
        "id": profile.id,
        "first_name": profile.first_name or None,
        "last_name": profile.last_name or None,
        "email": profile.email or None,
        "project_role": normalize_role(profile.role),
        "company": {
            "id": profile.workspace_id,
            "name": profile.workspace.name,
            "slug": profile.workspace.slug or None,
            "email": profile.workspace.email or None,
            "tax_code": profile.workspace.vat_number or None,
        },
        "user": (
            {
                "id": profile.user_id,
                "first_name": profile.user.first_name or None,
                "last_name": profile.user.last_name or None,
            }
            if profile.user_id and profile.user
            else None
        ),
    }


def get_company_contacts(*, company_id: int) -> dict:
    workspace = Workspace.objects.filter(id=company_id, is_active=True).first()
    if workspace is None:
        raise ValueError("Azienda non trovata.")

    contacts = list(
        Profile.objects.select_related("workspace", "user")
        .filter(
            workspace=workspace,
            is_active=True,
            role__in=[WorkspaceRole.OWNER, WorkspaceRole.DELEGATE],
        )
        .order_by("role", "first_name", "last_name", "id")
    )
    serialized_contacts = [serialize_company_contact(profile) for profile in contacts]
    return {
        "companyId": workspace.id,
        "contacts": serialized_contacts,
        "preferredContact": serialized_contacts[0] if serialized_contacts else None,
    }


def guess_extension_from_name(name: str | None, fallback: str = ".jpg") -> str:
    suffix = Path(name or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return fallback


def attach_profile_photo_from_temp_path(
    profile: Profile,
    *,
    temp_photo_path: str = "",
    overwrite: bool = False,
) -> bool:
    if not temp_photo_path or (profile.photo and not overwrite):
        return False
    if not default_storage.exists(temp_photo_path):
        return False

    file_name = Path(temp_photo_path).name or "profile-photo.jpg"
    with default_storage.open(temp_photo_path, "rb") as handle:
        profile.photo.save(file_name, File(handle), save=True)
    return True


def attach_profile_photo_from_remote_url(
    profile: Profile,
    *,
    remote_picture_url: str = "",
    overwrite: bool = False,
) -> bool:
    if not remote_picture_url or (profile.photo and not overwrite):
        return False

    try:
        with urlopen(remote_picture_url, timeout=5) as response:
            content = response.read()
            content_type = response.headers.get("Content-Type", "")
    except Exception:
        return False

    if not content:
        return False

    normalized_content_type = content_type.split(";", 1)[0].strip().lower()
    extension = mimetypes.guess_extension(normalized_content_type) or ""
    if extension == ".jpe":
        extension = ".jpg"
    if not extension:
        extension = guess_extension_from_name(urlparse(remote_picture_url).path)

    profile.photo.save(
        f"remote-avatar{extension}",
        optimize_media_content(
            filename=f"remote-avatar{extension}",
            content=content,
            content_type=content_type,
        ),
        save=True,
    )
    return True


def attach_profile_photo(
    profile: Profile,
    *,
    temp_photo_path: str = "",
    remote_picture_url: str = "",
    overwrite: bool = False,
) -> bool:
    if attach_profile_photo_from_temp_path(
        profile,
        temp_photo_path=temp_photo_path,
        overwrite=overwrite,
    ):
        return True
    return attach_profile_photo_from_remote_url(
        profile,
        remote_picture_url=remote_picture_url,
        overwrite=overwrite,
    )


def attach_profile_photo_from_user(
    profile: Profile,
    *,
    user,
    overwrite: bool = False,
) -> bool:
    if not user or not getattr(user, "photo", None) or (profile.photo and not overwrite):
        return False

    user_photo_name = (getattr(user.photo, "name", "") or "").strip()
    if not user_photo_name or not default_storage.exists(user_photo_name):
        return False

    file_name = Path(user_photo_name).name or "main-profile-photo.jpg"
    with default_storage.open(user_photo_name, "rb") as handle:
        profile.photo.save(file_name, File(handle), save=True)
    return True


def hydrate_profile_from_main_profile(
    profile: Profile,
    *,
    user=None,
    overwrite_missing_only: bool = True,
) -> Profile:
    if not user:
        return profile

    update_fields: list[str] = []
    candidate_first_name = (getattr(user, "first_name", "") or "").strip()
    candidate_last_name = (getattr(user, "last_name", "") or "").strip()
    candidate_phone = (getattr(user, "phone", "") or "").strip()
    candidate_language = (getattr(user, "language", "") or "").strip()
    candidate_phone_verified_at = getattr(user, "phone_verified_at", None)

    if candidate_first_name and (not profile.first_name or not overwrite_missing_only):
        if profile.first_name != candidate_first_name:
            profile.first_name = candidate_first_name
            update_fields.append("first_name")
    if candidate_last_name and (not profile.last_name or not overwrite_missing_only):
        if profile.last_name != candidate_last_name:
            profile.last_name = candidate_last_name
            update_fields.append("last_name")
    if candidate_phone and (not profile.phone or not overwrite_missing_only):
        if profile.phone != candidate_phone:
            profile.phone = candidate_phone
            update_fields.append("phone")
        if profile.phone_verified_at != candidate_phone_verified_at:
            profile.phone_verified_at = candidate_phone_verified_at
            update_fields.append("phone_verified_at")
    if candidate_language and (not profile.language or not overwrite_missing_only):
        if profile.language != candidate_language:
            profile.language = candidate_language
            update_fields.append("language")

    if update_fields:
        profile.save(update_fields=sorted(set(update_fields)))

    attach_profile_photo_from_user(
        profile,
        user=user,
        overwrite=not overwrite_missing_only,
    )
    return profile


def update_profile_identity(
    profile: Profile,
    *,
    email: str,
    user=None,
    role: str | None = None,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    language: str = "it",
    position: str = "",
    temp_photo_path: str = "",
    remote_picture_url: str = "",
) -> Profile:
    update_fields: list[str] = []

    normalized_email = normalize_email(email)
    normalized_first_name = (first_name or "").strip()
    normalized_last_name = (last_name or "").strip()
    normalized_phone = (phone or "").strip()
    normalized_language = (language or "it").strip() or "it"
    normalized_position = (position or "").strip()

    if normalized_email and profile.email != normalized_email:
        profile.email = normalized_email
        update_fields.append("email")

    normalized_role = normalize_role(role, default=profile.role)
    if normalized_role and profile.role != normalized_role:
        profile.role = normalized_role
        update_fields.append("role")

    if normalized_first_name and profile.first_name != normalized_first_name:
        profile.first_name = normalized_first_name
        update_fields.append("first_name")
    if normalized_last_name and profile.last_name != normalized_last_name:
        profile.last_name = normalized_last_name
        update_fields.append("last_name")

    if normalized_phone and profile.phone != normalized_phone:
        profile.phone = normalized_phone
        profile.phone_verified_at = None
        update_fields.extend(["phone", "phone_verified_at"])
    elif (
        normalized_phone
        and user is not None
        and getattr(user, "phone_verified_at", None) is not None
        and normalized_phone == (getattr(user, "phone", "") or "").strip()
        and profile.phone_verified_at != getattr(user, "phone_verified_at", None)
    ):
        profile.phone_verified_at = getattr(user, "phone_verified_at", None)
        update_fields.append("phone_verified_at")

    if normalized_language and profile.language != normalized_language:
        profile.language = normalized_language
        update_fields.append("language")

    if normalized_position and profile.position != normalized_position:
        profile.position = normalized_position
        update_fields.append("position")

    if update_fields:
        profile.save(update_fields=sorted(set(update_fields)))

    attach_profile_photo(
        profile,
        temp_photo_path=temp_photo_path,
        remote_picture_url=remote_picture_url,
    )
    hydrate_profile_from_main_profile(profile, user=user, overwrite_missing_only=True)
    return profile


@transaction.atomic
def update_current_workspace_profile_settings(
    user,
    *,
    claims: dict | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    language: str | None = None,
    position: str | None = None,
) -> dict:
    from edilcloud.modules.identity.services import sync_user_main_identity

    profile = resolve_active_workspace_profile(
        user,
        profile_id=resolve_claimed_profile_id(claims=claims),
    )
    next_first_name = profile.first_name if first_name is None else (first_name or "").strip()
    next_last_name = profile.last_name if last_name is None else (last_name or "").strip()
    next_phone = profile.phone if phone is None else (phone or "").strip()
    next_language = profile.language if language is None else (language or "").strip()
    next_position = profile.position if position is None else (position or "").strip()

    sync_user_main_identity(
        user,
        first_name=next_first_name,
        last_name=next_last_name,
        phone=next_phone or "",
        language=next_language or "it",
        mark_phone_verified=bool(getattr(user, "phone_verified_at", None)),
    )
    profile = update_profile_identity(
        profile,
        email=user.email,
        user=user,
        first_name=user.first_name,
        last_name=user.last_name,
        phone=user.phone or "",
        language=user.language or "it",
        position=next_position or "",
    )
    return serialize_current_workspace_profile(profile)


@transaction.atomic
def create_workspace_for_user(
    user,
    *,
    company_name: str,
    company_email: str = "",
    company_phone: str = "",
    company_website: str = "",
    company_vat_number: str = "",
    company_description: str = "",
    company_logo=None,
    workspace_type: str = "",
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    language: str = "it",
    position: str = "",
    profile_photo_path: str = "",
    remote_picture_url: str = "",
):
    """Create the first workspace for a user and return the auth context bound to its owner profile."""
    workspace_name = company_name.strip()
    if not workspace_name:
        raise ValueError("Il nome workspace e obbligatorio.")
    from edilcloud.modules.billing.services import (
        assert_workspace_creation_allowed,
        ensure_workspace_attached_to_owner_account,
    )

    assert_workspace_creation_allowed(user)

    prepared_company_logo = optimize_media_for_storage(company_logo) if company_logo else None
    workspace = Workspace.objects.create(
        name=workspace_name,
        email=(company_email or user.email or "").strip(),
        phone=company_phone.strip(),
        website=company_website.strip(),
        vat_number=company_vat_number.strip(),
        description=company_description.strip(),
        logo=prepared_company_logo,
        workspace_type=workspace_type.strip(),
    )
    profile = Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name=(first_name or user.first_name).strip(),
        last_name=(last_name or user.last_name).strip(),
        phone=phone.strip(),
        language=(language or user.language or "it").strip() or "it",
        position=position.strip(),
    )
    update_profile_identity(
        profile,
        email=user.email,
        user=user,
        first_name=profile.first_name,
        last_name=profile.last_name,
        phone=profile.phone,
        language=profile.language,
        position=profile.position,
        temp_photo_path=profile_photo_path,
        remote_picture_url=remote_picture_url,
    )

    if first_name.strip() or last_name.strip() or language.strip():
        user.first_name = profile.first_name
        user.last_name = profile.last_name
        user.language = profile.language
        user.save(update_fields=["first_name", "last_name", "language"])

    ensure_workspace_attached_to_owner_account(workspace, owner_user=user)

    from edilcloud.modules.identity.services import (
        authenticated_response_from_payload,
        build_auth_payload,
    )

    auth_payload = build_auth_payload(user, profile_id=profile.id)
    return {
        "workspace": serialize_workspace(workspace),
        "profile": serialize_profile(profile),
        "auth": authenticated_response_from_payload(auth_payload),
    }


def get_manageable_profile(user, workspace_id: int) -> Profile:
    profile = (
        Profile.objects.select_related("workspace")
        .filter(
            user=user,
            workspace_id=workspace_id,
            is_active=True,
            workspace__is_active=True,
            role__in=MANAGEABLE_ROLES,
        )
        .first()
    )
    if profile is None:
        raise ValueError("Non hai permessi per gestire questo workspace.")
    return profile


def get_manageable_current_profile(user, *, profile_id: int | None = None) -> Profile:
    profile = resolve_active_workspace_profile(user, profile_id=profile_id)
    if profile.role not in MANAGEABLE_ROLES:
        raise ValueError("Non hai permessi per gestire questo workspace.")
    return profile


def is_workspace_invite_active(invite: WorkspaceInvite) -> bool:
    return (
        invite.accepted_at is None
        and (invite.expires_at is None or invite.expires_at >= timezone.now())
    )


def encode_workspace_team_member_id(*, profile: Profile | None = None, invite: WorkspaceInvite | None = None) -> int:
    if profile is not None:
        return profile.id
    if invite is not None:
        return -invite.id
    raise ValueError("Membro workspace non valido.")


def serialize_workspace_invite_member(invite: WorkspaceInvite) -> dict:
    return {
        "id": encode_workspace_team_member_id(invite=invite),
        "first_name": invite.first_name,
        "last_name": invite.last_name,
        "email": invite.email,
        "phone": None,
        "mobile": None,
        "language": None,
        "position": invite.position or None,
        "role": invite.role,
        "photo": None,
        "company_invitation_date": invite.created_at,
        "profile_invitation_date": None,
        "invitation_refuse_date": invite.refused_at,
        "can_access_files": True,
        "can_access_chat": True,
        "user": None,
    }


def get_workspace_pending_invite(*, workspace: Workspace, email: str) -> WorkspaceInvite | None:
    normalized_email = normalize_email(email)
    if not normalized_email:
        return None
    return (
        WorkspaceInvite.objects.filter(
            workspace=workspace,
            email__iexact=normalized_email,
            accepted_at__isnull=True,
        )
        .order_by("-created_at", "-id")
        .first()
    )


def ensure_workspace_email_available(
    *,
    workspace: Workspace,
    email: str,
    ignore_profile_id: int | None = None,
    ignore_invite_id: int | None = None,
) -> None:
    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValueError("L'email e obbligatoria.")

    existing_profile = Profile.objects.filter(
        workspace=workspace,
        email__iexact=normalized_email,
    )
    if ignore_profile_id is not None:
        existing_profile = existing_profile.exclude(id=ignore_profile_id)
    if existing_profile.exists():
        raise ValueError("Esiste gia un membro con questa email nel workspace.")

    existing_invite = WorkspaceInvite.objects.filter(
        workspace=workspace,
        email__iexact=normalized_email,
        accepted_at__isnull=True,
    )
    if ignore_invite_id is not None:
        existing_invite = existing_invite.exclude(id=ignore_invite_id)
    if existing_invite.exists():
        raise ValueError("Esiste gia un invito attivo per questa email.")


def refresh_workspace_invite(
    invite: WorkspaceInvite,
    *,
    invited_by,
    email: str,
    role: str,
    first_name: str = "",
    last_name: str = "",
    position: str = "",
    expires_in_days: int = 14,
    reset_codes: bool = False,
) -> WorkspaceInvite:
    invite.invited_by = invited_by
    invite.email = normalize_email(email)
    invite.role = normalize_role(role)
    invite.first_name = (first_name or "").strip()
    invite.last_name = (last_name or "").strip()
    invite.position = (position or "").strip()
    invite.expires_at = timezone.now() + timedelta(days=max(1, expires_in_days))
    invite.refused_at = None
    update_fields = [
        "invited_by",
        "email",
        "role",
        "first_name",
        "last_name",
        "position",
        "expires_at",
        "refused_at",
        "updated_at",
    ]
    if reset_codes:
        invite.uidb36 = generate_uidb36()
        invite.token = generate_token()
        invite.invite_code = WorkspaceInvite.build_unique_invite_code()
        update_fields.extend(["uidb36", "token", "invite_code"])
    invite.save(update_fields=sorted(set(update_fields)))
    return invite


def send_workspace_invite(manager_profile: Profile, invite: WorkspaceInvite) -> None:
    send_workspace_invite_email(
        to_email=invite.email,
        workspace_name=manager_profile.workspace.name,
        inviter_name=manager_profile.member_name,
        role_label=invite.get_role_display(),
        invite_code=invite.invite_code,
        invite_url=build_invite_direct_url(invite),
        registration_url=build_invite_registration_url(invite),
    )


def build_invite_registration_url(invite: WorkspaceInvite) -> str:
    from django.conf import settings

    return (
        f"{settings.APP_FRONTEND_URL}/auth/register"
        f"?invite_uidb36={invite.uidb36}&invite_token={invite.token}"
    )


def build_invite_direct_url(invite: WorkspaceInvite) -> str:
    from django.conf import settings

    return f"{settings.APP_FRONTEND_URL}/invite/{invite.uidb36}/{invite.token}"


@transaction.atomic
def create_workspace_invite(
    user,
    *,
    workspace_id: int,
    email: str,
    role: str = WorkspaceRole.WORKER,
    first_name: str = "",
    last_name: str = "",
    position: str = "",
    expires_in_days: int = 14,
):
    """Create and send a workspace invite that can be accepted from onboarding or while signed in."""
    manager_profile = get_manageable_profile(user, workspace_id)
    from edilcloud.modules.billing.services import assert_workspace_seat_available

    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValueError("L'email dell'invitato e obbligatoria.")
    if normalized_email == normalize_email(manager_profile.email):
        raise ValueError("Non puoi invitare il tuo stesso profilo nel workspace.")

    existing_invite = get_workspace_pending_invite(
        workspace=manager_profile.workspace,
        email=normalized_email,
    )
    if existing_invite is None:
        assert_workspace_seat_available(
            manager_profile.workspace,
            reserve_pending_invite=True,
        )
        ensure_workspace_email_available(
            workspace=manager_profile.workspace,
            email=normalized_email,
        )
        invite = WorkspaceInvite.objects.create(
            workspace=manager_profile.workspace,
            invited_by=user,
            email=normalized_email,
            role=normalize_role(role),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            position=position.strip(),
            expires_at=timezone.now() + timedelta(days=max(1, expires_in_days)),
        )
    else:
        invite = refresh_workspace_invite(
            existing_invite,
            invited_by=user,
            email=normalized_email,
            role=role,
            first_name=first_name,
            last_name=last_name,
            position=position,
            expires_in_days=expires_in_days,
            reset_codes=True,
        )

    send_workspace_invite(manager_profile, invite)
    return serialize_workspace_invite(invite)


def serialize_workspace_invite(invite: WorkspaceInvite) -> dict:
    return {
        "id": invite.id,
        "invite_code": invite.invite_code,
        "uidb36": invite.uidb36,
        "token": invite.token,
        "email": invite.email,
        "role": invite.role,
        "position": invite.position or None,
        "accepted_at": invite.accepted_at,
        "expires_at": invite.expires_at,
        "refused_at": invite.refused_at,
        "company": serialize_workspace(invite.workspace),
    }


def list_pending_invites(user) -> list[dict]:
    invites = (
        WorkspaceInvite.objects.select_related("workspace")
        .filter(
            email__iexact=user.email,
            accepted_at__isnull=True,
            refused_at__isnull=True,
        )
        .order_by("-created_at", "-id")
    )

    now = timezone.now()
    results: list[dict] = []
    for invite in invites:
        if invite.expires_at and invite.expires_at < now:
            continue
        results.append(serialize_workspace_invite(invite))
    return results


def get_pending_invite_by_code(*, invite_code: str, email: str) -> WorkspaceInvite | None:
    normalized_code = normalize_invite_code(invite_code)
    normalized_email = normalize_email(email)
    if not normalized_code or not normalized_email:
        return None

    invite = (
        WorkspaceInvite.objects.select_related("workspace")
        .filter(
            invite_code=normalized_code,
            email__iexact=normalized_email,
            accepted_at__isnull=True,
            refused_at__isnull=True,
        )
        .first()
    )
    if invite is None:
        return None
    if invite.expires_at and invite.expires_at < timezone.now():
        return None
    return invite


def accept_workspace_invite_record(
    user,
    *,
    invite: WorkspaceInvite,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    language: str = "it",
    position: str = "",
    temp_photo_path: str = "",
    remote_picture_url: str = "",
):
    """Attach a user to the invited workspace and hydrate the member profile with onboarding data."""
    if invite.accepted_at is not None:
        raise ValueError("Invito workspace gia accettato.")
    if invite.refused_at is not None:
        raise ValueError("Invito workspace rifiutato. Chiedi un nuovo invito.")
    if invite.email.lower() != user.email.lower():
        raise ValueError("Questo invito non appartiene all'utente autenticato.")
    if invite.expires_at and invite.expires_at < timezone.now():
        raise ValueError("Invito workspace scaduto.")

    existing_profile = Profile.objects.filter(
        workspace=invite.workspace,
        user=user,
        is_active=True,
    ).first()
    if existing_profile is None:
        from edilcloud.modules.billing.services import assert_workspace_seat_available

        assert_workspace_seat_available(invite.workspace)

    profile, created = Profile.objects.get_or_create(
        workspace=invite.workspace,
        user=user,
        defaults={
            "email": user.email,
            "role": normalize_role(invite.role),
            "first_name": invite.first_name.strip() or first_name.strip() or user.first_name,
            "last_name": invite.last_name.strip() or last_name.strip() or user.last_name,
            "phone": phone.strip(),
            "language": (language or user.language or "it").strip() or "it",
            "position": invite.position.strip() or position.strip(),
        },
    )
    if not created:
        update_profile_identity(
            profile,
            email=user.email,
            user=user,
            role=invite.role,
            first_name=invite.first_name.strip() or first_name.strip() or profile.first_name,
            last_name=invite.last_name.strip() or last_name.strip() or profile.last_name,
            phone=phone.strip() or profile.phone,
            language=(language or profile.language or "it").strip() or "it",
            position=invite.position.strip() or position.strip() or profile.position,
            temp_photo_path=temp_photo_path,
            remote_picture_url=remote_picture_url,
        )
    else:
        attach_profile_photo(
            profile,
            temp_photo_path=temp_photo_path,
            remote_picture_url=remote_picture_url,
        )
        hydrate_profile_from_main_profile(profile, user=user, overwrite_missing_only=True)

    invite.accepted_by = user
    invite.accepted_at = timezone.now()
    invite.save(update_fields=["accepted_by", "accepted_at", "updated_at"])

    from edilcloud.modules.identity.services import (
        authenticated_response_from_payload,
        build_auth_payload,
    )

    auth_payload = build_auth_payload(user, profile_id=profile.id)
    return {
        "workspace": serialize_workspace(invite.workspace),
        "profile": serialize_profile(profile),
        "auth": authenticated_response_from_payload(auth_payload),
    }


@transaction.atomic
def accept_workspace_invite(
    user,
    *,
    uidb36: str,
    token: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    language: str = "it",
    position: str = "",
    temp_photo_path: str = "",
    remote_picture_url: str = "",
):
    invite = (
        WorkspaceInvite.objects.select_related("workspace")
        .filter(uidb36=uidb36, token=token)
        .first()
    )
    if invite is None:
        raise ValueError("Invito workspace non valido.")

    return accept_workspace_invite_record(
        user,
        invite=invite,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        language=language,
        position=position,
        temp_photo_path=temp_photo_path,
        remote_picture_url=remote_picture_url,
    )


@transaction.atomic
def accept_workspace_invite_by_code(
    user,
    *,
    invite_code: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    language: str = "it",
    position: str = "",
    temp_photo_path: str = "",
    remote_picture_url: str = "",
):
    invite = get_pending_invite_by_code(invite_code=invite_code, email=user.email)
    if invite is None:
        raise ValueError("Codice invito non valido o scaduto.")

    return accept_workspace_invite_record(
        user,
        invite=invite,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        language=language,
        position=position,
        temp_photo_path=temp_photo_path,
        remote_picture_url=remote_picture_url,
    )


def resolve_workspace_team_member(manager_profile: Profile, member_id: int) -> tuple[str, Profile | WorkspaceInvite]:
    if member_id < 0:
        invite = (
            WorkspaceInvite.objects.select_related("workspace")
            .filter(
                id=abs(member_id),
                workspace=manager_profile.workspace,
                accepted_at__isnull=True,
            )
            .first()
        )
        if invite is None:
            raise ValueError("Invito workspace non trovato.")
        return ("invite", invite)

    profile = (
        Profile.objects.select_related("workspace", "user")
        .filter(id=member_id, workspace=manager_profile.workspace)
        .first()
    )
    if profile is None:
        raise ValueError("Membro workspace non trovato.")
    return ("profile", profile)


def create_current_workspace_member(
    user,
    *,
    claims: dict,
    email: str,
    role: str = WorkspaceRole.WORKER,
    first_name: str = "",
    last_name: str = "",
    position: str = "",
    expires_in_days: int = 14,
) -> dict:
    manager_profile = get_manageable_current_profile(
        user,
        profile_id=int(claims.get("main_profile")) if claims.get("main_profile") is not None else None,
    )
    invite = create_workspace_invite(
        user,
        workspace_id=manager_profile.workspace_id,
        email=email,
        role=role,
        first_name=first_name,
        last_name=last_name,
        position=position,
        expires_in_days=expires_in_days,
    )
    workspace_invite = WorkspaceInvite.objects.get(id=invite["id"])
    return serialize_workspace_invite_member(workspace_invite)


def update_current_workspace_member(
    user,
    *,
    claims: dict,
    member_id: int,
    email: str | None = None,
    role: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    language: str | None = None,
    position: str | None = None,
    phone: str | None = None,
    can_access_files: bool | None = None,
    can_access_chat: bool | None = None,
) -> dict:
    del can_access_files, can_access_chat
    manager_profile = get_manageable_current_profile(
        user,
        profile_id=int(claims.get("main_profile")) if claims.get("main_profile") is not None else None,
    )
    member_type, target = resolve_workspace_team_member(manager_profile, member_id)

    if member_type == "invite":
        invite = target
        updated_email = normalize_email(email or invite.email)
        ensure_workspace_email_available(
            workspace=manager_profile.workspace,
            email=updated_email,
            ignore_invite_id=invite.id,
        )
        refresh_workspace_invite(
            invite,
            invited_by=user,
            email=updated_email,
            role=role or invite.role,
            first_name=first_name if first_name is not None else invite.first_name,
            last_name=last_name if last_name is not None else invite.last_name,
            position=position if position is not None else invite.position,
            expires_in_days=max(1, ((invite.expires_at - timezone.now()).days if invite.expires_at else 14) or 14),
            reset_codes=False,
        )
        return serialize_workspace_invite_member(invite)

    profile = target
    if profile.id == manager_profile.id and role and normalize_role(role, default=profile.role) != profile.role:
        raise ValueError("Non puoi cambiare il ruolo del tuo profilo attivo da questo pannello.")
    update_profile_identity(
        profile,
        email=normalize_email(email or profile.email),
        user=profile.user,
        role=role or profile.role,
        first_name=first_name if first_name is not None else profile.first_name,
        last_name=last_name if last_name is not None else profile.last_name,
        phone=phone if phone is not None else profile.phone,
        language=language if language is not None else profile.language,
        position=position if position is not None else profile.position,
    )
    return serialize_workspace_team_member(profile)


def disable_current_workspace_member(user, *, claims: dict, member_id: int) -> dict:
    manager_profile = get_manageable_current_profile(
        user,
        profile_id=int(claims.get("main_profile")) if claims.get("main_profile") is not None else None,
    )
    member_type, target = resolve_workspace_team_member(manager_profile, member_id)
    if member_type != "profile":
        raise ValueError("Puoi disattivare solo profili gia attivi nel workspace.")
    profile = target
    if profile.id == manager_profile.id:
        raise ValueError("Non puoi disattivare il tuo profilo attivo.")
    if not profile.is_active:
        return serialize_workspace_team_member(profile)
    profile.is_active = False
    profile.save(update_fields=["is_active", "updated_at"])
    return serialize_workspace_team_member(profile)


def enable_current_workspace_member(user, *, claims: dict, member_id: int) -> dict:
    manager_profile = get_manageable_current_profile(
        user,
        profile_id=int(claims.get("main_profile")) if claims.get("main_profile") is not None else None,
    )
    member_type, target = resolve_workspace_team_member(manager_profile, member_id)
    if member_type != "profile":
        raise ValueError("Puoi riattivare solo profili disattivati.")
    profile = target
    if profile.is_active:
        return serialize_workspace_team_member(profile)
    profile.is_active = True
    profile.save(update_fields=["is_active", "updated_at"])
    return serialize_workspace_team_member(profile)


def resend_current_workspace_invite(user, *, claims: dict, member_id: int) -> dict:
    manager_profile = get_manageable_current_profile(
        user,
        profile_id=int(claims.get("main_profile")) if claims.get("main_profile") is not None else None,
    )
    member_type, target = resolve_workspace_team_member(manager_profile, member_id)
    if member_type != "invite":
        raise ValueError("Puoi reinviare solo inviti workspace in attesa o rifiutati.")
    invite = target
    refresh_workspace_invite(
        invite,
        invited_by=user,
        email=invite.email,
        role=invite.role,
        first_name=invite.first_name,
        last_name=invite.last_name,
        position=invite.position,
        expires_in_days=14,
        reset_codes=True,
    )
    send_workspace_invite(manager_profile, invite)
    return serialize_workspace_invite_member(invite)


def delete_current_workspace_member(user, *, claims: dict, member_id: int) -> dict:
    manager_profile = get_manageable_current_profile(
        user,
        profile_id=int(claims.get("main_profile")) if claims.get("main_profile") is not None else None,
    )
    member_type, target = resolve_workspace_team_member(manager_profile, member_id)
    if member_type != "invite":
        raise ValueError("La rimozione definitiva e supportata solo per inviti in attesa o rifiutati.")
    invite = target
    invite.delete()
    return {
        "status": "deleted",
        "detail": "Invito workspace rimosso.",
    }


@transaction.atomic
def refuse_workspace_invite(*, uidb36: str, token: str) -> dict:
    invite = (
        WorkspaceInvite.objects.select_related("workspace")
        .filter(uidb36=uidb36, token=token)
        .first()
    )
    if invite is None:
        raise ValueError("Invito workspace non valido.")
    if invite.accepted_at is not None:
        raise ValueError("Invito workspace gia accettato.")
    if invite.expires_at and invite.expires_at < timezone.now():
        raise ValueError("Invito workspace scaduto.")
    if invite.refused_at is None:
        invite.refused_at = timezone.now()
        invite.save(update_fields=["refused_at", "updated_at"])
    return {
        "status": "refused",
        "detail": "Invito workspace rifiutato.",
    }


def get_workspace_search_results(*, email: str, query: str, limit: int = 10) -> list[dict]:
    """Return the workspace search results enriched with membership and pending-request state."""
    normalized_query = (query or "").strip()
    normalized_email = normalize_email(email)
    if len("".join(tokenize_workspace_query(normalized_query))) < 2:
        return []

    workspace_queryset = (
        Workspace.objects.filter(is_active=True)
        .filter(build_workspace_search_filter(normalized_query))
        .order_by("name", "id")[:limit]
    )
    workspace_ids = [workspace.id for workspace in workspace_queryset]

    pending_invite_ids = set(
        WorkspaceInvite.objects.filter(
            workspace_id__in=workspace_ids,
            email__iexact=normalized_email,
            accepted_at__isnull=True,
        ).values_list("workspace_id", flat=True)
    )
    pending_request_ids = set(
        WorkspaceAccessRequest.objects.filter(
            workspace_id__in=workspace_ids,
            email__iexact=normalized_email,
            status=AccessRequestStatus.PENDING,
        ).values_list("workspace_id", flat=True)
    )

    existing_profile_ids: set[int] = set()
    user = get_user_model().objects.filter(email__iexact=normalized_email).first()
    if user is not None:
        existing_profile_ids = set(
            Profile.objects.filter(
                user=user,
                workspace_id__in=workspace_ids,
                is_active=True,
                workspace__is_active=True,
            ).values_list("workspace_id", flat=True)
        )

    return [
        {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "logo": file_url(workspace.logo),
            "workspace_type": workspace.workspace_type or None,
            "already_member": workspace.id in existing_profile_ids,
            "pending_invite": workspace.id in pending_invite_ids,
            "pending_access_request": workspace.id in pending_request_ids,
        }
        for workspace in workspace_queryset
    ]


def get_workspace_review_recipients(workspace: Workspace) -> list[dict]:
    profiles = (
        Profile.objects.filter(
            workspace=workspace,
            is_active=True,
            role__in=MANAGEABLE_ROLES,
        )
        .exclude(email="")
        .order_by("id")
    )

    recipients: list[dict] = []
    seen_emails: set[str] = set()
    for profile in profiles:
        email = normalize_email(profile.email)
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        recipients.append(
            {
                "email": email,
                "member_name": profile.member_name,
                "profile": profile,
            }
        )
    return recipients


def build_access_request_notification_body(access_request: WorkspaceAccessRequest) -> str:
    details: list[str] = []
    if access_request.position:
        details.append(f"Ruolo indicato: {access_request.position}.")
    if access_request.phone:
        details.append(f"Telefono: {access_request.phone}.")
    if access_request.message:
        details.append(f"Messaggio: {access_request.message}")
    return " ".join(details)


def build_access_request_notification_data(access_request: WorkspaceAccessRequest) -> dict:
    return {
        "workspace_id": access_request.workspace_id,
        "workspace_name": access_request.workspace.name,
        "access_request_id": access_request.id,
        "request_token": access_request.request_token,
        "status": access_request.status,
    }


def get_access_request_reviewer_profile(
    access_request: WorkspaceAccessRequest,
    *,
    reviewed_by,
) -> Profile | None:
    if reviewed_by is None:
        return None
    return (
        Profile.objects.select_related("workspace", "user")
        .filter(
            workspace=access_request.workspace,
            user=reviewed_by,
            is_active=True,
        )
        .first()
    )


def serialize_workspace_access_request(access_request: WorkspaceAccessRequest) -> dict:
    return {
        "id": access_request.id,
        "status": access_request.status,
        "email": access_request.email,
        "first_name": access_request.first_name,
        "last_name": access_request.last_name,
        "phone": access_request.phone or None,
        "language": access_request.language or None,
        "position": access_request.position or None,
        "message": access_request.message or None,
        "approved_at": access_request.approved_at,
        "refused_at": access_request.refused_at,
        "expires_at": access_request.expires_at,
        "company": serialize_workspace(access_request.workspace),
    }


@transaction.atomic
def create_workspace_access_request(
    user,
    *,
    workspace_id: int,
    email: str,
    first_name: str,
    last_name: str,
    phone: str,
    language: str,
    position: str = "",
    message: str = "",
    photo_path: str = "",
    picture_url: str = "",
    expires_in_days: int = 14,
):
    """Open a moderated workspace access request and notify reviewers by email."""
    workspace = Workspace.objects.filter(id=workspace_id, is_active=True).first()
    if workspace is None:
        raise ValueError("Workspace non valido.")

    normalized_email = normalize_email(email)
    if not normalized_email:
        raise ValueError("Email obbligatoria.")

    if Profile.objects.filter(
        workspace=workspace,
        user=user,
        is_active=True,
    ).exists():
        raise ValueError("Fai gia parte di questo workspace.")

    if WorkspaceInvite.objects.filter(
        workspace=workspace,
        email__iexact=normalized_email,
        accepted_at__isnull=True,
    ).exists():
        raise ValueError("Esiste gia un invito attivo per questa email.")

    existing_request = (
        WorkspaceAccessRequest.objects.filter(
            workspace=workspace,
            email__iexact=normalized_email,
            status=AccessRequestStatus.PENDING,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if existing_request is not None:
        raise ValueError("Hai gia una richiesta di accesso in attesa per questo workspace.")

    access_request = WorkspaceAccessRequest.objects.create(
        workspace=workspace,
        requested_by_user=user,
        email=normalized_email,
        first_name=(first_name or "").strip(),
        last_name=(last_name or "").strip(),
        phone=(phone or "").strip(),
        language=(language or "it").strip() or "it",
        position=(position or "").strip(),
        message=(message or "").strip(),
        photo_path=(photo_path or "").strip(),
        picture_url=(picture_url or "").strip(),
        expires_at=timezone.now() + timedelta(days=max(1, expires_in_days)),
    )

    review_recipients = get_workspace_review_recipients(workspace)
    if not review_recipients:
        raise ValueError("Questo workspace non ha owner o delegate contattabili.")

    requester_name = f"{access_request.first_name} {access_request.last_name}".strip() or normalized_email
    notification_body = build_access_request_notification_body(access_request)
    notification_data = build_access_request_notification_data(access_request)
    from edilcloud.modules.notifications.services import create_notification
    sender_profile = select_default_profile(user)

    for recipient in review_recipients:
        send_workspace_access_request_review_email(
            to_email=recipient["email"],
            reviewer_name=recipient["member_name"],
            workspace_name=workspace.name,
            requester_name=requester_name,
            requester_email=normalized_email,
            requester_phone=access_request.phone,
            position=access_request.position,
            message=access_request.message,
            approve_path=f"/access-requests/{access_request.id}/{access_request.request_token}/approve/",
            refuse_path=f"/access-requests/{access_request.id}/{access_request.request_token}/refuse/",
        )
        create_notification(
            recipient_profile=recipient["profile"],
            sender_user=user,
            sender_profile=sender_profile,
            subject=f"{requester_name} ha richiesto accesso a {workspace.name}",
            body=notification_body,
            kind="workspace.access_request.created",
            sender_position=access_request.position,
            content_type="workspace_access_request",
            object_id=access_request.id,
            data={
                **notification_data,
                "category": "workspace",
                "action": "created",
                "target_tab": "overview",
            },
        )

    return {
        "status": "request_sent",
        "detail": "La richiesta di accesso e stata inviata al workspace selezionato.",
        "request": serialize_workspace_access_request(access_request),
    }


def get_access_request_by_token(*, request_id: int, token: str) -> WorkspaceAccessRequest:
    access_request = (
        WorkspaceAccessRequest.objects.select_related("workspace", "requested_by_user")
        .filter(id=request_id, request_token=token)
        .first()
    )
    if access_request is None:
        raise ValueError("Richiesta di accesso non valida.")
    if access_request.status != AccessRequestStatus.PENDING:
        raise ValueError("Questa richiesta non e piu disponibile.")
    if access_request.expires_at and access_request.expires_at < timezone.now():
        raise ValueError("Questa richiesta di accesso e scaduta.")
    return access_request


def provision_workspace_access_profile(access_request: WorkspaceAccessRequest) -> Profile:
    """Materialize the approved access request into an active workspace profile."""
    requested_user = access_request.requested_by_user
    if requested_user is None:
        normalized_email = normalize_email(access_request.email)
        user_model = get_user_model()
        requested_user = user_model.objects.filter(email__iexact=normalized_email).first()
        if requested_user is None:
            requested_user = user_model.objects.create_user(
                email=normalized_email,
                password=None,
                username=normalized_email.split("@", 1)[0],
                first_name=access_request.first_name,
                last_name=access_request.last_name,
                phone=(access_request.phone or "").strip() or None,
                phone_verified_at=timezone.now() if access_request.phone.strip() else None,
                language=access_request.language or "it",
                is_active=True,
            )
        access_request.requested_by_user = requested_user
        access_request.save(update_fields=["requested_by_user", "updated_at"])

    from edilcloud.modules.identity.services import sync_user_main_identity

    sync_user_main_identity(
        requested_user,
        first_name=access_request.first_name or requested_user.first_name,
        last_name=access_request.last_name or requested_user.last_name,
        phone=access_request.phone,
        language=access_request.language or requested_user.language or "it",
        profile_photo_path=access_request.photo_path,
        remote_picture_url=access_request.picture_url,
        mark_phone_verified=bool(access_request.phone),
    )

    profile, _created = Profile.objects.get_or_create(
        workspace=access_request.workspace,
        user=requested_user,
        defaults={
            "email": requested_user.email,
            "role": WorkspaceRole.WORKER,
            "first_name": access_request.first_name,
            "last_name": access_request.last_name,
            "phone": access_request.phone,
            "language": access_request.language or requested_user.language or "it",
            "position": access_request.position,
        },
    )
    update_profile_identity(
        profile,
        email=requested_user.email,
        user=requested_user,
        role=WorkspaceRole.WORKER,
        first_name=access_request.first_name or requested_user.first_name,
        last_name=access_request.last_name or requested_user.last_name,
        phone=access_request.phone,
        language=access_request.language or requested_user.language or "it",
        position=access_request.position,
        temp_photo_path=access_request.photo_path,
        remote_picture_url=access_request.picture_url,
    )
    return profile


@transaction.atomic
def approve_workspace_access_request(
    *,
    request_id: int,
    token: str,
    reviewed_by=None,
):
    """Approve an access request, create the profile if needed and notify the requester."""
    access_request = get_access_request_by_token(request_id=request_id, token=token)
    profile = provision_workspace_access_profile(access_request)

    access_request.status = AccessRequestStatus.APPROVED
    access_request.reviewed_by = reviewed_by
    access_request.approved_at = timezone.now()
    access_request.save(
        update_fields=["status", "reviewed_by", "approved_at", "updated_at"]
    )

    reviewer_profile = get_access_request_reviewer_profile(
        access_request,
        reviewed_by=reviewed_by,
    )

    send_workspace_access_approved_email(
        to_email=access_request.email,
        workspace_name=access_request.workspace.name,
        member_name=profile.member_name,
    )

    from edilcloud.modules.notifications.services import create_notification

    create_notification(
        recipient_profile=profile,
        sender_user=reviewed_by,
        sender_profile=reviewer_profile,
        subject=f"{access_request.workspace.name} ha approvato la tua richiesta",
        body="Adesso puoi accedere al workspace con il profilo appena creato.",
        kind="workspace.access_request.approved",
        sender_company_name=access_request.workspace.name,
        sender_position=reviewer_profile.position if reviewer_profile else "",
        content_type="workspace_access_request",
        object_id=access_request.id,
        data={
            **build_access_request_notification_data(access_request),
            "category": "workspace",
            "action": "approved",
            "target_tab": "overview",
        },
    )

    return {
        "status": "approved",
        "detail": "Richiesta approvata correttamente.",
        "request": serialize_workspace_access_request(access_request),
    }


@transaction.atomic
def refuse_workspace_access_request(
    *,
    request_id: int,
    token: str,
    reviewed_by=None,
):
    """Reject a pending workspace access request without creating any profile."""
    access_request = get_access_request_by_token(request_id=request_id, token=token)
    access_request.status = AccessRequestStatus.REFUSED
    access_request.reviewed_by = reviewed_by
    access_request.refused_at = timezone.now()
    access_request.save(
        update_fields=["status", "reviewed_by", "refused_at", "updated_at"]
    )

    requester_profile = None
    if access_request.requested_by_user is not None:
        requester_profile = select_default_profile(access_request.requested_by_user)

    if requester_profile is not None:
        reviewer_profile = get_access_request_reviewer_profile(
            access_request,
            reviewed_by=reviewed_by,
        )
        from edilcloud.modules.notifications.services import create_notification

        create_notification(
            recipient_profile=requester_profile,
            sender_user=reviewed_by,
            sender_profile=reviewer_profile,
            subject=f"{access_request.workspace.name} ha rifiutato la tua richiesta",
            body="La richiesta non e stata approvata. Puoi contattare il workspace o riprovare piu avanti.",
            kind="workspace.access_request.refused",
            sender_company_name=access_request.workspace.name,
            sender_position=reviewer_profile.position if reviewer_profile else "",
            content_type="workspace_access_request",
            object_id=access_request.id,
            data={
                **build_access_request_notification_data(access_request),
                "category": "workspace",
                "action": "refused",
                "target_tab": "overview",
            },
        )

    return {
        "status": "refused",
        "detail": "Richiesta rifiutata.",
        "request": serialize_workspace_access_request(access_request),
    }
