import json

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceInvite, WorkspaceRole


def auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"JWT {token}"}


@pytest.mark.django_db
def test_create_workspace_returns_profile_and_auth_payload():
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
                "username_or_email": user.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    token = login_response.json()["token"]

    response = client.post(
        "/api/v1/workspaces",
        data=json.dumps(
            {
                "company_name": "Aurora Costruzioni",
                "company_email": "info@aurora.test",
                "company_phone": "+39 011 000000",
                "company_website": "https://aurora.test",
                "company_vat_number": "IT12345678901",
                "company_description": "General contractor",
                "workspace_type": "impresa",
                "first_name": "Mario",
                "last_name": "Rossi",
                "phone": "+39 333 1234567",
                "language": "it",
                "position": "Project manager",
            }
        ),
        content_type="application/json",
        **auth_header(token),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["workspace"]["name"] == "Aurora Costruzioni"
    assert payload["profile"]["role"] == WorkspaceRole.OWNER
    assert payload["profile"]["company"]["slug"] == "aurora-costruzioni"
    assert payload["auth"]["main_profile"] == payload["profile"]["id"]
    assert payload["auth"]["extra"]["profile"]["company"] == payload["workspace"]["id"]

    profile = Profile.objects.get(id=payload["profile"]["id"])
    assert profile.workspace.name == "Aurora Costruzioni"
    assert profile.position == "Project manager"


@pytest.mark.django_db
def test_login_and_refresh_can_target_real_workspace_profile():
    user = get_user_model().objects.create_user(
        email="owner@example.com",
        password="devpass123",
        username="owner",
        first_name="Owner",
        last_name="User",
        language="it",
    )
    workspace_one = Workspace.objects.create(name="Workspace One")
    workspace_two = Workspace.objects.create(name="Workspace Two")
    first_profile = Profile.objects.create(
        workspace=workspace_one,
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name="Owner",
        last_name="User",
        language="it",
    )
    second_profile = Profile.objects.create(
        workspace=workspace_two,
        user=user,
        email=user.email,
        role=WorkspaceRole.WORKER,
        first_name="Owner",
        last_name="User",
        language="it",
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
    login_payload = login_response.json()
    assert login_payload["main_profile"] == first_profile.id
    assert login_payload["extra"]["profile"]["company"] == workspace_one.id

    refresh_response = client.post(
        f"/api/v1/auth/token/refresh/{second_profile.id}",
        data=json.dumps({"refresh_token": login_payload["refresh_token"]}),
        content_type="application/json",
    )

    assert refresh_response.status_code == 200
    refresh_payload = refresh_response.json()
    assert refresh_payload["main_profile"] == second_profile.id
    assert refresh_payload["extra"]["profile"]["company"] == workspace_two.id


@pytest.mark.django_db
def test_workspace_list_and_invite_acceptance_flow():
    owner = get_user_model().objects.create_user(
        email="owner@example.com",
        password="devpass123",
        username="owner",
        first_name="Owner",
        last_name="User",
        language="it",
    )
    invited = get_user_model().objects.create_user(
        email="invitee@example.com",
        password="devpass123",
        username="invitee",
        first_name="Anna",
        last_name="Bianchi",
        language="it",
    )
    workspace = Workspace.objects.create(name="Studio Ferretti")
    Profile.objects.create(
        workspace=workspace,
        user=owner,
        email=owner.email,
        role=WorkspaceRole.OWNER,
        first_name="Owner",
        last_name="User",
        language="it",
    )
    client = Client()

    owner_login = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": owner.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    owner_token = owner_login.json()["token"]

    invite_response = client.post(
        f"/api/v1/workspaces/{workspace.id}/invites",
        data=json.dumps(
            {
                "email": invited.email,
                "role": "d",
                "position": "Direzione lavori",
            }
        ),
        content_type="application/json",
        **auth_header(owner_token),
    )
    assert invite_response.status_code == 201
    invite_payload = invite_response.json()
    assert invite_payload["company"]["id"] == workspace.id
    assert invite_payload["role"] == "d"

    invited_client = Client()
    invited_login = invited_client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": invited.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    invited_token = invited_login.json()["token"]

    pending_response = invited_client.get(
        "/api/v1/workspaces/invites/pending",
        **auth_header(invited_token),
    )
    assert pending_response.status_code == 200
    pending_payload = pending_response.json()
    assert len(pending_payload) == 1
    assert pending_payload[0]["uidb36"] == invite_payload["uidb36"]

    accept_response = invited_client.post(
        f"/api/v1/workspaces/invites/{invite_payload['uidb36']}/{invite_payload['token']}/accept",
        content_type="application/json",
        **auth_header(invited_token),
    )
    assert accept_response.status_code == 200
    accept_payload = accept_response.json()
    assert accept_payload["profile"]["role"] == "d"
    assert accept_payload["auth"]["main_profile"] == accept_payload["profile"]["id"]

    workspaces_response = invited_client.get(
        "/api/v1/workspaces",
        **auth_header(invited_token),
    )
    assert workspaces_response.status_code == 200
    workspaces_payload = workspaces_response.json()
    assert workspaces_payload == [
        {
            "profileId": accept_payload["profile"]["id"],
            "companyId": workspace.id,
            "companyName": "Studio Ferretti",
            "companySlug": workspace.slug,
            "companyLogo": None,
            "role": "d",
            "memberName": "Anna Bianchi",
            "photo": None,
        }
    ]

    assert Profile.objects.filter(workspace=workspace, user=invited).exists()


@pytest.mark.django_db
def test_invited_workspace_profile_inherits_main_profile_phone_and_photo():
    owner = get_user_model().objects.create_user(
        email="owner.inherit@example.com",
        password="devpass123",
        username="owner-inherit",
        first_name="Owner",
        last_name="Inherit",
        language="it",
    )
    invited = get_user_model().objects.create_user(
        email="invitee.inherit@example.com",
        password="devpass123",
        username="invitee-inherit",
        first_name="Elena",
        last_name="Villa",
        phone="+39333999888",
        phone_verified_at=timezone.now(),
        language="it",
    )
    invited.photo.save(
        "main-avatar.png",
        SimpleUploadedFile("main-avatar.png", b"fake-main-avatar", content_type="image/png"),
        save=True,
    )
    workspace = Workspace.objects.create(name="Impresa Eredita")
    Profile.objects.create(
        workspace=workspace,
        user=owner,
        email=owner.email,
        role=WorkspaceRole.OWNER,
        first_name="Owner",
        last_name="Inherit",
        language="it",
    )
    client = Client()

    owner_login = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": owner.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    owner_token = owner_login.json()["token"]

    invite_response = client.post(
        f"/api/v1/workspaces/{workspace.id}/invites",
        data=json.dumps(
            {
                "email": invited.email,
                "role": "w",
            }
        ),
        content_type="application/json",
        **auth_header(owner_token),
    )
    assert invite_response.status_code == 201
    invite_payload = invite_response.json()

    invited_client = Client()
    invited_login = invited_client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": invited.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    invited_token = invited_login.json()["token"]

    accept_response = invited_client.post(
        f"/api/v1/workspaces/invites/{invite_payload['uidb36']}/{invite_payload['token']}/accept",
        content_type="application/json",
        **auth_header(invited_token),
    )
    assert accept_response.status_code == 200

    profile = Profile.objects.get(workspace=workspace, user=invited)
    assert profile.phone == invited.phone
    assert profile.phone_verified_at == invited.phone_verified_at
    assert profile.photo.name
    assert profile.photo.name.startswith("workspaces/profiles/photos/")


@pytest.mark.django_db
def test_current_workspace_members_support_waiting_refused_resend_and_delete_flow():
    owner = get_user_model().objects.create_user(
        email="owner.team@example.com",
        password="devpass123",
        username="owner-team",
        first_name="Owner",
        last_name="Team",
        language="it",
    )
    workspace = Workspace.objects.create(name="Team Flow Workspace")
    Profile.objects.create(
        workspace=workspace,
        user=owner,
        email=owner.email,
        role=WorkspaceRole.OWNER,
        first_name="Owner",
        last_name="Team",
        language="it",
    )
    client = Client()
    login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": owner.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    token = login_response.json()["token"]

    invite_response = client.post(
        "/api/v1/workspaces/current/members",
        data=json.dumps(
            {
                "email": "collab@example.com",
                "first_name": "Sara",
                "last_name": "Verdi",
                "role": "m",
                "position": "Capocantiere",
            }
        ),
        content_type="application/json",
        **auth_header(token),
    )
    assert invite_response.status_code == 201
    invite_member = invite_response.json()
    assert invite_member["id"] < 0
    assert invite_member["role"] == WorkspaceRole.MANAGER

    members_response = client.get(
        "/api/v1/workspaces/current/members",
        **auth_header(token),
    )
    assert members_response.status_code == 200
    members_payload = members_response.json()
    assert len(members_payload["waiting"]) == 1
    assert members_payload["waiting"][0]["email"] == "collab@example.com"
    invite = WorkspaceInvite.objects.get(id=abs(invite_member["id"]))

    refuse_response = client.post(
        f"/api/v1/workspaces/invites/{invite.uidb36}/{invite.token}/refuse",
        content_type="application/json",
    )
    assert refuse_response.status_code == 200
    assert refuse_response.json()["status"] == "refused"

    refused_members_response = client.get(
        "/api/v1/workspaces/current/members",
        **auth_header(token),
    )
    refused_members_payload = refused_members_response.json()
    assert refused_members_payload["waiting"] == []
    assert len(refused_members_payload["refused"]) == 1
    assert refused_members_payload["refused"][0]["id"] == invite_member["id"]
    assert refused_members_payload["refused"][0]["invitation_refuse_date"] is not None

    resend_response = client.post(
        f"/api/v1/workspaces/current/members/{invite_member['id']}/resend",
        content_type="application/json",
        **auth_header(token),
    )
    assert resend_response.status_code == 200
    resent_member = resend_response.json()
    assert resent_member["id"] == invite_member["id"]
    assert resent_member["invitation_refuse_date"] is None

    waiting_again_response = client.get(
        "/api/v1/workspaces/current/members",
        **auth_header(token),
    )
    waiting_again_payload = waiting_again_response.json()
    assert len(waiting_again_payload["waiting"]) == 1
    assert waiting_again_payload["refused"] == []

    delete_response = client.delete(
        f"/api/v1/workspaces/current/members/{invite_member['id']}",
        **auth_header(token),
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["status"] == "deleted"
    assert WorkspaceInvite.objects.filter(id=abs(invite_member["id"])).exists() is False


@pytest.mark.django_db
def test_current_workspace_members_can_update_disable_and_enable_profiles():
    owner = get_user_model().objects.create_user(
        email="owner.manage@example.com",
        password="devpass123",
        username="owner-manage",
        first_name="Owner",
        last_name="Manage",
        language="it",
    )
    worker = get_user_model().objects.create_user(
        email="worker.manage@example.com",
        password="devpass123",
        username="worker-manage",
        first_name="Giulia",
        last_name="Neri",
        language="it",
    )
    workspace = Workspace.objects.create(name="Manage Flow Workspace")
    Profile.objects.create(
        workspace=workspace,
        user=owner,
        email=owner.email,
        role=WorkspaceRole.OWNER,
        first_name="Owner",
        last_name="Manage",
        language="it",
    )
    worker_profile = Profile.objects.create(
        workspace=workspace,
        user=worker,
        email=worker.email,
        role=WorkspaceRole.WORKER,
        first_name="Giulia",
        last_name="Neri",
        language="it",
        position="Operativa",
    )
    client = Client()
    login_response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": owner.email,
                "password": "devpass123",
            }
        ),
        content_type="application/json",
    )
    token = login_response.json()["token"]

    update_response = client.put(
        f"/api/v1/workspaces/current/members/{worker_profile.id}",
        data=json.dumps(
            {
                "role": "m",
                "position": "Project Manager",
            }
        ),
        content_type="application/json",
        **auth_header(token),
    )
    assert update_response.status_code == 200
    assert update_response.json()["role"] == WorkspaceRole.MANAGER
    worker_profile.refresh_from_db()
    assert worker_profile.role == WorkspaceRole.MANAGER
    assert worker_profile.position == "Project Manager"

    disable_response = client.post(
        f"/api/v1/workspaces/current/members/{worker_profile.id}/disable",
        content_type="application/json",
        **auth_header(token),
    )
    assert disable_response.status_code == 200
    worker_profile.refresh_from_db()
    assert worker_profile.is_active is False

    members_after_disable = client.get(
        "/api/v1/workspaces/current/members",
        **auth_header(token),
    ).json()
    assert len(members_after_disable["disabled"]) == 1
    assert members_after_disable["disabled"][0]["id"] == worker_profile.id

    enable_response = client.post(
        f"/api/v1/workspaces/current/members/{worker_profile.id}/enable",
        content_type="application/json",
        **auth_header(token),
    )
    assert enable_response.status_code == 200
    worker_profile.refresh_from_db()
    assert worker_profile.is_active is True

    delete_profile_response = client.delete(
        f"/api/v1/workspaces/current/members/{worker_profile.id}",
        **auth_header(token),
    )
    assert delete_profile_response.status_code == 400
    assert "solo per inviti" in delete_profile_response.json()["detail"]


@pytest.mark.django_db
def test_current_workspace_profile_settings_can_be_read_and_updated():
    user = get_user_model().objects.create_user(
        email="profile.settings@example.com",
        password="devpass123",
        username="profile-settings",
        first_name="Alessandro",
        last_name="Coti",
        language="it",
        phone="+393331112233",
    )
    workspace = Workspace.objects.create(name="Edilcloud Test")
    profile = Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name="Alessandro",
        last_name="Coti",
        phone="+393331112233",
        language="it",
        position="Owner",
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
    token = login_response.json()["token"]

    get_response = client.get(
        "/api/v1/workspaces/current/profile",
        **auth_header(token),
    )
    assert get_response.status_code == 200
    get_payload = get_response.json()
    assert get_payload["email"] == user.email
    assert get_payload["company_name"] == workspace.name
    assert get_payload["position"] == "Owner"

    patch_response = client.patch(
        "/api/v1/workspaces/current/profile",
        data=json.dumps(
            {
                "first_name": "Sandro",
                "last_name": "Cantiere",
                "phone": "+39 339 777 4444",
                "language": "en",
                "position": "General manager",
            }
        ),
        content_type="application/json",
        **auth_header(token),
    )
    assert patch_response.status_code == 200
    patch_payload = patch_response.json()
    assert patch_payload["first_name"] == "Sandro"
    assert patch_payload["last_name"] == "Cantiere"
    assert patch_payload["phone"] == "+393397774444"
    assert patch_payload["language"] == "en"
    assert patch_payload["position"] == "General manager"

    user.refresh_from_db()
    profile.refresh_from_db()
    assert user.first_name == "Sandro"
    assert user.last_name == "Cantiere"
    assert user.phone == "+393397774444"
    assert user.language == "en"
    assert profile.first_name == "Sandro"
    assert profile.last_name == "Cantiere"
    assert profile.phone == "+393397774444"
    assert profile.language == "en"
    assert profile.position == "General manager"
