import json
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.storage import FileSystemStorage
from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile

from edilcloud.modules.identity import services as identity_services
from edilcloud.modules.billing.services import ensure_workspace_attached_to_owner_account
from edilcloud.modules.workspaces.models import (
    AccessRequestStatus,
    Profile,
    Workspace,
    WorkspaceAccessRequest,
    WorkspaceInvite,
    WorkspaceRole,
)


def extract_email_code(index: int = -1) -> str:
    assert mail.outbox
    match = re.search(r"\b(\d{6})\b", mail.outbox[index].body)
    assert match is not None
    return match.group(1)


def extract_access_code() -> str:
    return extract_email_code()


def create_workspace_with_owner(*, workspace_name: str, email: str = "owner@example.com"):
    owner = get_user_model().objects.create_user(
        email=email,
        password="devpass123",
        username=email.split("@")[0],
        first_name="Owner",
        last_name="User",
        language="it",
    )
    workspace = Workspace.objects.create(name=workspace_name, email=email)
    workspace.profiles.create(
        user=owner,
        email=owner.email,
        role=WorkspaceRole.OWNER,
        first_name="Owner",
        last_name="User",
        language="it",
    )
    ensure_workspace_attached_to_owner_account(workspace, owner_user=owner)
    return owner, workspace


@pytest.mark.django_db
def test_register_endpoint_creates_user():
    client = Client()

    response = client.post(
        "/api/v1/auth/register",
        data=json.dumps(
            {
                "email": "mario.rossi@example.com",
                "password": "strong-pass-123",
                "first_name": "Mario",
                "last_name": "Rossi",
                "username": "mrossi",
                "language": "it",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["email"] == "mario.rossi@example.com"
    assert payload["username"] == "mrossi"
    assert get_user_model().objects.filter(email="mario.rossi@example.com").exists()


@pytest.mark.django_db
def test_register_rejects_weak_password():
    client = Client()

    response = client.post(
        "/api/v1/auth/register",
        data=json.dumps(
            {
                "email": "weak.password@example.com",
                "password": "12345678",
                "first_name": "Weak",
                "last_name": "Password",
                "username": "weak-password",
                "language": "it",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert not get_user_model().objects.filter(email="weak.password@example.com").exists()


@pytest.mark.django_db
def test_login_verify_refresh_and_me_flow():
    user = get_user_model().objects.create_user(
        email="owner@example.com",
        password="devpass123",
        username="owner",
        first_name="Owner",
        last_name="User",
        language="it",
    )
    client = Client()

    login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": "owner@example.com",
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )

    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload["status"] == "authenticated"
    assert login_payload["user"] == "owner@example.com"
    assert login_payload["main_profile"] == user.id
    assert login_payload["is_superuser"] is False
    assert login_payload["is_staff"] is False
    assert login_payload["extra"]["profile"]["id"] == user.id
    assert login_payload["refresh_token"]
    assert login_payload["session_id"]

    token = login_payload["token"]
    refresh_token = login_payload["refresh_token"]

    verify_response = client.post(
        "/api/v1/auth/token/verify",
        data=json.dumps({"token": token}),
        content_type="application/json",
    )
    assert verify_response.status_code == 200
    verify_payload = verify_response.json()
    assert verify_payload["status"] == "authenticated"
    assert verify_payload["extra"]["profile"]["role"] == "o"
    assert verify_payload["is_superuser"] is False
    assert verify_payload["is_staff"] is False

    refresh_response = client.post(
        f"/api/v1/auth/token/refresh/{user.id}",
        data=json.dumps({"refresh_token": refresh_token}),
        content_type="application/json",
    )
    assert refresh_response.status_code == 200
    refresh_payload = refresh_response.json()
    assert refresh_payload["status"] == "authenticated"
    assert refresh_payload["main_profile"] == user.id
    assert refresh_payload["orig_iat"] == login_payload["orig_iat"]
    assert refresh_payload["session_id"] == login_payload["session_id"]
    assert refresh_payload["is_superuser"] is False
    assert refresh_payload["is_staff"] is False
    assert refresh_payload["token"] != token
    assert refresh_payload["refresh_token"] != refresh_token

    stale_me_response = client.get(
        "/api/v1/auth/me",
        HTTP_AUTHORIZATION=f"JWT {token}",
    )
    assert stale_me_response.status_code == 401

    me_response = client.get(
        "/api/v1/auth/me",
        HTTP_AUTHORIZATION=f"JWT {refresh_payload['token']}",
    )
    assert me_response.status_code == 200
    me_payload = me_response.json()
    assert me_payload["email"] == "owner@example.com"
    assert me_payload["username"] == "owner"


@pytest.mark.django_db
def test_login_with_unknown_user_fails():
    client = Client()

    response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": "missing@example.com",
                "password": "wrong",
            }
        ),
        content_type="application/json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_superuser_auth_payload_exposes_admin_flags():
    user = get_user_model().objects.create_superuser(
        email="superuser@example.com",
        password="devpass123",
        username="superuser",
    )
    client = Client()

    login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": user.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )

    assert login_response.status_code == 200
    payload = login_response.json()
    assert payload["is_superuser"] is True
    assert payload["is_staff"] is True

    verify_response = client.post(
        "/api/v1/auth/token/verify",
        data=json.dumps({"token": payload["token"]}),
        content_type="application/json",
    )
    assert verify_response.status_code == 200
    verify_payload = verify_response.json()
    assert verify_payload["is_superuser"] is True
    assert verify_payload["is_staff"] is True


@pytest.mark.django_db
def test_logout_revokes_current_session():
    get_user_model().objects.create_user(
        email="logout@example.com",
        password="devpass123",
        username="logout-user",
        first_name="Logout",
        last_name="User",
        language="it",
    )
    client = Client()

    login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": "logout@example.com",
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    login_payload = login_response.json()

    logout_response = client.post(
        "/api/v1/auth/logout",
        data=json.dumps({"refresh_token": login_payload["refresh_token"]}),
        content_type="application/json",
    )
    assert logout_response.status_code == 200

    me_response = client.get(
        "/api/v1/auth/me",
        HTTP_AUTHORIZATION=f"JWT {login_payload['token']}",
    )
    assert me_response.status_code == 401

    refresh_response = client.post(
        f"/api/v1/auth/token/refresh/{login_payload['main_profile']}",
        data=json.dumps({"refresh_token": login_payload["refresh_token"]}),
        content_type="application/json",
    )
    assert refresh_response.status_code == 401


@pytest.mark.django_db
def test_password_reset_flow_updates_password_and_revokes_sessions():
    user = get_user_model().objects.create_user(
        email="reset@example.com",
        password="OldPassword123!",
        username="reset-user",
        first_name="Reset",
        last_name="User",
        language="it",
    )
    client = Client()

    login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": user.email,
                "password": "OldPassword123!",
            }
        ),
        content_type="application/json",
    )
    login_payload = login_response.json()

    request_response = client.post(
        "/api/v1/auth/password-reset/request",
        data=json.dumps({"email": user.email}),
        content_type="application/json",
    )
    assert request_response.status_code == 200
    assert request_response.json()["detail"]
    reset_code = extract_email_code()

    confirm_response = client.post(
        "/api/v1/auth/password-reset/confirm",
        data=json.dumps(
            {
                "email": user.email,
                "code": reset_code,
                "new_password": "NewPassword123!",
            }
        ),
        content_type="application/json",
    )
    assert confirm_response.status_code == 200

    stale_me_response = client.get(
        "/api/v1/auth/me",
        HTTP_AUTHORIZATION=f"JWT {login_payload['token']}",
    )
    assert stale_me_response.status_code == 401

    old_login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": user.email,
                "password": "OldPassword123!",
            }
        ),
        content_type="application/json",
    )
    assert old_login_response.status_code == 400

    new_login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": user.email,
                "password": "NewPassword123!",
            }
        ),
        content_type="application/json",
    )
    assert new_login_response.status_code == 200


@pytest.mark.django_db
def test_login_rate_limit_returns_429_after_repeated_failures():
    client = Client()
    blocked_username = "blocked-login@example.com"

    for _ in range(10):
        response = client.post(
            "/api/v1/auth/login",
            data=json.dumps(
                {
                    "username_or_email": blocked_username,
                    "password": "wrong",
                }
            ),
            content_type="application/json",
        )
        assert response.status_code == 400

    blocked_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": blocked_username,
                "password": "wrong",
            }
        ),
        content_type="application/json",
    )
    assert blocked_response.status_code == 429


@pytest.mark.django_db
def test_access_code_confirm_authenticates_existing_workspace_user():
    user = get_user_model().objects.create_user(
        email="owner@example.com",
        password="unused-pass",
        username="owner",
        first_name="Mario",
        last_name="Rossi",
        language="it",
    )
    workspace = Workspace.objects.create(name="Aurora SRL")
    workspace.profiles.create(
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name="Mario",
        last_name="Rossi",
        language="it",
    )
    client = Client()

    request_response = client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": user.email}),
        content_type="application/json",
    )
    assert request_response.status_code == 200

    code = extract_access_code()
    confirm_response = client.post(
        "/api/v1/auth/access-code/confirm",
        data=json.dumps({"email": user.email, "code": code}),
        content_type="application/json",
    )

    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert payload["status"] == "authenticated"
    assert payload["user"] == user.email
    assert payload["main_profile"] is not None


@pytest.mark.django_db
def test_access_code_request_sends_transactional_email():
    client = Client()

    response = client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": "mail.test@example.com"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "code_sent"
    assert payload.get("dev_code") is None
    assert payload.get("debug_flow_token") is None
    assert len(mail.outbox) == 1

    message = mail.outbox[0]
    assert message.subject == "Il tuo codice EdilCloud"
    assert message.from_email == settings.REGISTRATION_FROM_EMAIL
    assert "Il tuo codice di accesso" in message.body
    assert re.search(r"\b\d{6}\b", message.body) is not None
    assert len(message.alternatives) == 1
    html_body, mimetype = message.alternatives[0]
    assert mimetype == "text/html"
    assert "EdilCloud" in html_body
    assert "mail.test@example.com" not in html_body


@pytest.mark.django_db
def test_access_code_onboarding_profile_and_complete_flow_creates_workspace():
    client = Client()
    email = "new.user@example.com"

    request_response = client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": email}),
        content_type="application/json",
    )
    assert request_response.status_code == 200

    code = extract_access_code()
    confirm_response = client.post(
        "/api/v1/auth/access-code/confirm",
        data=json.dumps({"email": email, "code": code}),
        content_type="application/json",
    )
    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.json()
    assert confirm_payload["status"] == "onboarding_required"
    onboarding_token = confirm_payload["onboarding_token"]

    profile_response = client.post(
        "/api/v1/auth/onboarding/profile",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "first_name": "Giulia",
                "last_name": "Verdi",
                "phone": "+39 333 000000",
                "language": "it",
            }
        ),
        content_type="application/json",
    )
    assert profile_response.status_code == 200
    profile_payload = profile_response.json()
    assert profile_payload["prefill"]["first_name"] == "Giulia"
    assert profile_payload["prefill"]["phone"] == "+39333000000"

    complete_response = client.post(
        "/api/v1/auth/onboarding/complete",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "first_name": "Giulia",
                "last_name": "Verdi",
                "phone": "+39 333 000000",
                "language": "it",
                "company_name": "Cantiere Futuro",
                "company_email": email,
            }
        ),
        content_type="application/json",
    )
    assert complete_response.status_code == 200
    complete_payload = complete_response.json()
    assert complete_payload["status"] == "authenticated"
    assert complete_payload["onboarding_completed"] is True

    user = get_user_model().objects.get(email=email)
    assert user.workspace_profiles.filter(workspace__name="Cantiere Futuro").exists()


@pytest.mark.django_db
def test_email_access_code_onboarding_prefill_leaves_names_empty():
    client = Client()
    email = "a.coti1987@example.com"

    request_response = client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": email}),
        content_type="application/json",
    )
    assert request_response.status_code == 200

    code = extract_access_code()
    confirm_response = client.post(
        "/api/v1/auth/access-code/confirm",
        data=json.dumps({"email": email, "code": code}),
        content_type="application/json",
    )
    assert confirm_response.status_code == 200

    payload = confirm_response.json()
    assert payload["status"] == "onboarding_required"
    assert payload["prefill"]["email"] == email
    assert payload["prefill"]["first_name"] == ""
    assert payload["prefill"]["last_name"] == ""


@pytest.mark.django_db
def test_onboarding_profile_photo_upload_is_attached_to_created_profile():
    client = Client()
    email = "photo.user@example.com"

    request_response = client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": email}),
        content_type="application/json",
    )
    assert request_response.status_code == 200

    code = extract_access_code()
    confirm_response = client.post(
        "/api/v1/auth/access-code/confirm",
        data=json.dumps({"email": email, "code": code}),
        content_type="application/json",
    )
    onboarding_token = confirm_response.json()["onboarding_token"]

    photo = SimpleUploadedFile("avatar.png", b"fake-image-content", content_type="image/png")
    profile_response = client.post(
        "/api/v1/auth/onboarding/profile",
        data={
            "onboarding_token": onboarding_token,
            "first_name": "Luca",
            "last_name": "Bianchi",
            "phone": "+39 349 100200",
            "language": "it",
            "photo": photo,
        },
    )
    assert profile_response.status_code == 200
    picture_url = profile_response.json()["prefill"]["picture"]
    assert picture_url
    assert "/media/onboarding/profile-photos/" in picture_url

    complete_response = client.post(
        "/api/v1/auth/onboarding/complete",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "company_name": "Avatar Build",
                "company_email": email,
            }
        ),
        content_type="application/json",
    )
    assert complete_response.status_code == 200

    user = get_user_model().objects.get(email=email)
    assert user.photo.name
    assert user.photo.name.startswith("identity/users/photos/")
    assert user.phone == "+39349100200"
    assert user.phone_verified_at is not None

    profile = Profile.objects.get(user__email=email, workspace__name="Avatar Build")
    assert profile.photo.name
    assert profile.photo.name.startswith("workspaces/profiles/photos/")
    assert profile.phone == "+39349100200"


@pytest.mark.django_db
def test_cache_remote_onboarding_picture_creates_missing_media_parent_directory(tmp_path, monkeypatch):
    media_root = tmp_path / "missing-media-root"
    storage = FileSystemStorage(location=str(media_root), base_url="/media/")
    monkeypatch.setattr(identity_services, "default_storage", storage)

    class FakeResponse:
        def __init__(self):
            self.headers = {"Content-Type": "image/png"}

        def read(self):
            return b"fake-image-content"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(identity_services, "urlopen", lambda *_args, **_kwargs: FakeResponse())

    stored_path, stored_url = identity_services.cache_remote_onboarding_picture(
        email="google.user@example.com",
        remote_url="https://example.com/avatar.png",
    )

    assert stored_path.startswith("onboarding/profile-photos/")
    assert stored_url.startswith("/media/onboarding/profile-photos/")
    assert media_root.joinpath(Path(stored_path)).exists()


@pytest.mark.django_db
def test_google_auth_accepts_oauth_access_token(monkeypatch):
    client = Client()

    monkeypatch.setattr(
        identity_services,
        "verify_google_access_token",
        lambda access_token: {
            "email": "google.access@example.com",
            "email_verified": True,
            "given_name": "Google",
            "family_name": "Access",
            "locale": "it",
            "picture": "https://example.com/avatar.png",
            "sub": "google-sub-123",
        },
    )
    monkeypatch.setattr(
        identity_services,
        "cache_remote_onboarding_picture",
        lambda **_kwargs: ("", ""),
    )

    response = client.post(
        "/api/v1/auth/google",
        data=json.dumps({"access_token": "google-oauth-access-token"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "onboarding_required"
    assert payload["prefill"]["email"] == "google.access@example.com"
    assert payload["prefill"]["first_name"] == "Google"
    assert payload["prefill"]["last_name"] == "Access"


@pytest.mark.django_db
def test_google_auth_rejects_missing_google_token():
    client = Client()

    response = client.post(
        "/api/v1/auth/google",
        data=json.dumps({}),
        content_type="application/json",
    )

    assert response.status_code == 400
    assert "mancante" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_onboarding_rejects_phone_already_bound_to_another_main_profile():
    get_user_model().objects.create_user(
        email="existing.phone@example.com",
        password="devpass123",
        username="existing-phone",
        first_name="Phone",
        last_name="Owner",
        phone="+39333111222",
        language="it",
    )
    client = Client()
    email = "second.phone@example.com"

    client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": email}),
        content_type="application/json",
    )
    code = extract_access_code()
    confirm_response = client.post(
        "/api/v1/auth/access-code/confirm",
        data=json.dumps({"email": email, "code": code}),
        content_type="application/json",
    )
    onboarding_token = confirm_response.json()["onboarding_token"]

    profile_response = client.post(
        "/api/v1/auth/onboarding/profile",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "first_name": "Secondo",
                "last_name": "Utente",
                "phone": "+39 333 111222",
                "language": "it",
            }
        ),
        content_type="application/json",
    )

    assert profile_response.status_code == 400
    assert "supporto" in profile_response.json()["detail"].lower()


@pytest.mark.django_db
def test_onboarding_can_list_and_accept_workspace_invite():
    _owner, workspace = create_workspace_with_owner(
        workspace_name="Invito Cantiere",
        email="owner.invito@example.com",
    )
    invited_email = "invitee@example.com"
    WorkspaceInvite.objects.create(
        workspace=workspace,
        email=invited_email,
        role=WorkspaceRole.DELEGATE,
    )
    client = Client()

    request_response = client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": invited_email}),
        content_type="application/json",
    )
    assert request_response.status_code == 200

    code = extract_access_code()
    confirm_response = client.post(
        "/api/v1/auth/access-code/confirm",
        data=json.dumps({"email": invited_email, "code": code}),
        content_type="application/json",
    )
    onboarding_token = confirm_response.json()["onboarding_token"]

    invites_response = client.get(
        f"/api/v1/auth/onboarding/invites?onboarding_token={onboarding_token}",
    )
    assert invites_response.status_code == 200
    invites_payload = invites_response.json()
    assert len(invites_payload) == 1
    invite = invites_payload[0]
    assert invite["company"]["name"] == "Invito Cantiere"

    profile_response = client.post(
        "/api/v1/auth/onboarding/profile",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "first_name": "Lorenzo",
                "last_name": "Conti",
                "phone": "+39 333 555444",
                "language": "it",
            }
        ),
        content_type="application/json",
    )
    assert profile_response.status_code == 200

    accept_response = client.post(
        f"/api/v1/auth/onboarding/invites/{invite['uidb36']}/{invite['token']}/accept",
        data=json.dumps({"onboarding_token": onboarding_token}),
        content_type="application/json",
    )
    assert accept_response.status_code == 200
    accept_payload = accept_response.json()
    assert accept_payload["status"] == "authenticated"
    assert accept_payload["joined_workspace"] is True

    user = get_user_model().objects.get(email=invited_email)
    assert user.workspace_profiles.filter(workspace=workspace).exists()


@pytest.mark.django_db
def test_onboarding_can_accept_workspace_invite_by_code():
    _owner, workspace = create_workspace_with_owner(
        workspace_name="Codice Cantiere",
        email="owner.codice@example.com",
    )
    invited_email = "coded.invitee@example.com"
    invite = WorkspaceInvite.objects.create(
        workspace=workspace,
        email=invited_email,
        role=WorkspaceRole.WORKER,
    )
    client = Client()

    client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": invited_email}),
        content_type="application/json",
    )
    code = extract_access_code()
    confirm_response = client.post(
        "/api/v1/auth/access-code/confirm",
        data=json.dumps({"email": invited_email, "code": code}),
        content_type="application/json",
    )
    onboarding_token = confirm_response.json()["onboarding_token"]

    client.post(
        "/api/v1/auth/onboarding/profile",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "first_name": "Anna",
                "last_name": "Neri",
                "phone": "+39 333 111222",
                "language": "it",
            }
        ),
        content_type="application/json",
    )

    accept_response = client.post(
        "/api/v1/auth/onboarding/invites/code/accept",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "invite_code": invite.invite_code,
            }
        ),
        content_type="application/json",
    )

    assert accept_response.status_code == 200
    assert accept_response.json()["joined_workspace"] is True
    assert get_user_model().objects.get(email=invited_email).workspace_profiles.filter(
        workspace=workspace
    ).exists()


@pytest.mark.django_db
def test_workspace_invite_email_contains_invite_code():
    inviter = get_user_model().objects.create_user(
        email="delegate@example.com",
        password="devpass123",
        username="delegate",
        first_name="Delegate",
        last_name="User",
        language="it",
    )
    workspace = Workspace.objects.create(name="Invite Mail SRL", email="delegate@example.com")
    profile = workspace.profiles.create(
        user=inviter,
        email=inviter.email,
        role=WorkspaceRole.OWNER,
        first_name="Delegate",
        last_name="User",
        language="it",
    )
    ensure_workspace_attached_to_owner_account(workspace, owner_user=inviter)
    client = Client()
    login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": inviter.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    token = login_response.json()["token"]

    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/invites",
        data=json.dumps(
            {
                "email": "invite.mail@example.com",
                "role": "w",
            }
        ),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"JWT {token}",
    )

    assert response.status_code == 201
    invite_code = response.json()["invite_code"]
    assert invite_code
    assert len(mail.outbox) == 1
    assert invite_code in mail.outbox[0].body
    assert profile.member_name in mail.outbox[0].body


@pytest.mark.django_db
def test_onboarding_can_request_workspace_access_and_review_link_approves_profile():
    owner = get_user_model().objects.create_user(
        email="owner.review@example.com",
        password="devpass123",
        username="owner-review",
        first_name="Owner",
        last_name="Review",
        language="it",
    )
    workspace = Workspace.objects.create(name="Review Workspace")
    workspace.profiles.create(
        user=owner,
        email=owner.email,
        role=WorkspaceRole.OWNER,
        first_name="Owner",
        last_name="Review",
        language="it",
    )
    client = Client()
    request_email = "requester@example.com"

    client.post(
        "/api/v1/auth/access-code/request",
        data=json.dumps({"email": request_email}),
        content_type="application/json",
    )
    code = extract_access_code()
    confirm_response = client.post(
        "/api/v1/auth/access-code/confirm",
        data=json.dumps({"email": request_email, "code": code}),
        content_type="application/json",
    )
    onboarding_token = confirm_response.json()["onboarding_token"]

    profile_response = client.post(
        "/api/v1/auth/onboarding/profile",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "first_name": "Sara",
                "last_name": "Blu",
                "phone": "+39 347 1234567",
                "language": "it",
            }
        ),
        content_type="application/json",
    )
    assert profile_response.status_code == 200

    search_response = client.get(
        f"/api/v1/auth/onboarding/workspaces/search?onboarding_token={onboarding_token}&query=rev work",
    )
    assert search_response.status_code == 200
    assert search_response.json()[0]["name"] == "Review Workspace"

    access_response = client.post(
        f"/api/v1/auth/onboarding/workspaces/{workspace.id}/request-access",
        data=json.dumps(
            {
                "onboarding_token": onboarding_token,
                "position": "Geometra",
                "message": "Vorrei accedere al workspace.",
            }
        ),
        content_type="application/json",
    )
    assert access_response.status_code == 200
    access_payload = access_response.json()
    assert access_payload["status"] == "request_sent"

    access_request = WorkspaceAccessRequest.objects.get(email=request_email)
    assert access_request.status == AccessRequestStatus.PENDING
    assert len(mail.outbox) == 2
    review_email = mail.outbox[1]
    assert "Nuova richiesta di accesso" in review_email.subject

    approve_match = re.search(r"https?://[^/]+(/access-requests/[^\s]+/approve/)", review_email.body)
    assert approve_match is not None

    approve_response = client.get(approve_match.group(1))
    assert approve_response.status_code == 200
    assert WorkspaceAccessRequest.objects.get(id=access_request.id).status == AccessRequestStatus.APPROVED
    assert get_user_model().objects.get(email=request_email).workspace_profiles.filter(
        workspace=workspace
    ).exists()
    assert len(mail.outbox) == 3
    assert "Accesso approvato" in mail.outbox[2].subject
