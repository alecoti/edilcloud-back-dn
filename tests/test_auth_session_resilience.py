import json
from datetime import datetime, timedelta

import jwt
import pytest
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from edilcloud.modules.identity import services
from edilcloud.modules.identity.models import AuthTokenSession
from edilcloud.modules.workspaces.models import Workspace, WorkspaceRole


@pytest.fixture
def account(db):
    user = get_user_model().objects.create_user(
        email="session-resilience@example.com", password="devpass123", username="session-resilience"
    )
    workspace = Workspace.objects.create(name="Session A")
    profile = workspace.profiles.create(user=user, email=user.email, role=WorkspaceRole.OWNER)
    other = Workspace.objects.create(name="Session B")
    other_profile = other.profiles.create(user=user, email=user.email, role=WorkspaceRole.OWNER)
    return user, profile, other_profile


def refresh(client, token, profile_id=None):
    path = "/api/v1/auth/token/refresh"
    if profile_id is not None:
        path += f"/{profile_id}"
    return client.post(path, data=json.dumps({"refresh_token": token}), content_type="application/json")


@pytest.mark.django_db
def test_duplicate_refresh_returns_same_pair_without_revoking(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    first = refresh(Client(), initial["refresh_token"], profile.id)
    duplicate = refresh(Client(), initial["refresh_token"], profile.id)
    assert first.status_code == duplicate.status_code == 200
    assert first.json()["token"] == duplicate.json()["token"]
    assert first.json()["refresh_token"] == duplicate.json()["refresh_token"]
    assert AuthTokenSession.objects.get(session_token=initial["session_id"]).revoked_at is None


@pytest.mark.django_db
def test_refresh_keeps_unexpired_inflight_access_valid(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    assert refresh(Client(), initial["refresh_token"], profile.id).status_code == 200
    assert services.verify_user_token(initial["token"])["main_profile"] == profile.id


@pytest.mark.django_db
def test_automatic_refresh_uses_authoritative_workspace(account):
    user, profile, other_profile = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    switched = refresh(Client(), initial["refresh_token"], other_profile.id)
    assert switched.status_code == 200
    late_renewal = refresh(Client(), initial["refresh_token"])
    assert late_renewal.status_code == 200
    assert late_renewal.json()["main_profile"] == other_profile.id
    assert late_renewal.json()["refresh_token"] == switched.json()["refresh_token"]
    with pytest.raises(jwt.InvalidTokenError):
        services.verify_user_token(initial["token"])


@pytest.mark.django_db
def test_refresh_cannot_extend_absolute_lifetime(account, monkeypatch):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    tomorrow = timezone.now() + timedelta(days=1)

    class NextDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return tomorrow

    monkeypatch.setattr(services, "datetime", NextDay)
    renewed = refresh(Client(), initial["refresh_token"], profile.id)
    assert renewed.status_code == 200
    assert renewed.json()["refresh_exp"] <= initial["refresh_exp"]


@pytest.mark.django_db
def test_expired_access_token_and_refresh_as_access_are_rejected(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    claims = services.decode_access_token(initial["token"])
    claims["exp"] = 1
    with pytest.raises(jwt.ExpiredSignatureError):
        services.verify_user_token(services.encode_access_token(claims))
    with pytest.raises(jwt.InvalidTokenError):
        services.verify_user_token(initial["refresh_token"])


@pytest.mark.django_db
def test_unknown_signed_refresh_generation_revokes_family(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    claims = services.decode_refresh_token(initial["refresh_token"])
    claims["rti"] = "unknown-generation"
    replay = refresh(Client(), services.encode_refresh_token(claims), profile.id)
    assert replay.status_code == 401
    session = AuthTokenSession.objects.get(session_token=initial["session_id"])
    assert session.revoke_reason == "refresh_replay_detected"
    with pytest.raises(jwt.InvalidTokenError):
        services.verify_user_token(initial["token"])


@pytest.mark.django_db
def test_cross_user_workspace_denied_without_destroying_session(account):
    user, profile, _ = account
    stranger = get_user_model().objects.create_user(email="stranger@example.com", password="devpass123")
    workspace = Workspace.objects.create(name="Private")
    private_profile = workspace.profiles.create(user=stranger, email=stranger.email, role=WorkspaceRole.OWNER)
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    assert refresh(Client(), initial["refresh_token"], private_profile.id).status_code == 400
    assert services.verify_user_token(initial["token"])["main_profile"] == profile.id


@pytest.mark.django_db
def test_inactive_user_cannot_verify_or_refresh(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    user.is_active = False
    user.save(update_fields=["is_active"])
    verify = Client().post("/api/v1/auth/token/verify", data=json.dumps({"token": initial["token"]}), content_type="application/json")
    assert verify.status_code == 401
    assert refresh(Client(), initial["refresh_token"], profile.id).status_code == 401


@pytest.mark.django_db
def test_refresh_session_expired_server_side(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    AuthTokenSession.objects.filter(session_token=initial["session_id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert refresh(Client(), initial["refresh_token"], profile.id).status_code == 401


@pytest.mark.django_db
def test_legacy_sliding_session_cannot_bypass_absolute_timeout(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    AuthTokenSession.objects.filter(session_token=initial["session_id"]).update(created_at=timezone.now() - timedelta(seconds=settings.AUTH_SESSION_ABSOLUTE_TTL_SECONDS + 1))
    assert refresh(Client(), initial["refresh_token"]).status_code == 401
    with pytest.raises(jwt.InvalidTokenError):
        services.verify_user_token(initial["token"])


@pytest.mark.django_db
def test_refresh_reuse_outside_grace_revokes_family(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    assert refresh(Client(), initial["refresh_token"]).status_code == 200
    session = AuthTokenSession.objects.get(session_token=initial["session_id"])
    session.recent_refresh_jtis = [{"jti": entry["jti"], "until": 0} for entry in session.recent_refresh_jtis]
    session.save(update_fields=["recent_refresh_jtis"])
    assert refresh(Client(), initial["refresh_token"]).status_code == 401
    session.refresh_from_db()
    assert session.revoke_reason == "refresh_replay_detected"


@pytest.mark.django_db
def test_late_retry_after_multiple_rotations_returns_latest_pair(account):
    user, profile, other_profile = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    first = refresh(Client(), initial["refresh_token"]).json()
    second = refresh(Client(), first["refresh_token"], other_profile.id).json()
    late = refresh(Client(), initial["refresh_token"])
    assert late.status_code == 200
    assert late.json()["token"] == second["token"]
    assert late.json()["main_profile"] == other_profile.id


@pytest.mark.django_db
def test_logout_with_inflight_old_refresh_revokes_latest_pair(account):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    current = refresh(Client(), initial["refresh_token"]).json()
    services.logout_user(refresh_token=initial["refresh_token"])
    assert refresh(Client(), current["refresh_token"]).status_code == 401
    with pytest.raises(jwt.InvalidTokenError):
        services.verify_user_token(current["token"])


@pytest.mark.django_db
def test_rate_limit_does_not_block_another_session_behind_same_bff(account, monkeypatch):
    from edilcloud.modules.identity import api
    user, profile, _ = account
    cache.clear()
    monkeypatch.setattr(api, "REFRESH_RATE_LIMIT", (1, 600))
    one = services.issue_authenticated_response(user, profile_id=profile.id)
    two = services.issue_authenticated_response(user, profile_id=profile.id)
    assert refresh(Client(), one["refresh_token"]).status_code == 200
    assert refresh(Client(), one["refresh_token"]).status_code == 429
    assert refresh(Client(), two["refresh_token"]).status_code == 200
    cache.clear()


@pytest.mark.django_db
@pytest.mark.parametrize("mutation", ["expired", "wrong_audience", "wrong_type", "malformed_session", "missing_claim"])
def test_invalid_refresh_tokens_cannot_authorize(account, mutation):
    user, profile, _ = account
    initial = services.issue_authenticated_response(user, profile_id=profile.id)
    claims = services.decode_refresh_token(initial["refresh_token"])
    if mutation == "expired":
        claims["exp"] = 1
    elif mutation == "wrong_audience":
        claims["aud"] = settings.AUTH_TOKEN_AUDIENCE
    elif mutation == "wrong_type":
        claims["type"] = "access"
    elif mutation == "malformed_session":
        claims["sid"] = "not-a-uuid"
    else:
        del claims["rti"]
    assert refresh(Client(), services.encode_refresh_token(claims)).status_code == 401
