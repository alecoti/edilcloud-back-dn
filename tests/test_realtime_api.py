import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole
from edilcloud.platform.realtime.services import read_realtime_ticket


def auth_header(token: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"JWT {token}"}


def login_and_get_token(*, email: str, password: str) -> str:
    client = Client()
    response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": email,
                "password": password,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()["token"]


@pytest.mark.django_db
def test_notification_realtime_session_returns_cached_ticket_for_active_profile():
    user = get_user_model().objects.create_user(
        email="owner@example.com",
        password="devpass123",
        username="owner",
        first_name="Owner",
        last_name="User",
        language="it",
    )
    workspace = Workspace.objects.create(name="Realtime Workspace")
    profile = Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=WorkspaceRole.OWNER,
        first_name="Owner",
        last_name="User",
        language="it",
    )
    token = login_and_get_token(email=user.email, password="devpass123")
    client = Client()

    response = client.get(
        "/api/v1/notifications/realtime/session",
        **auth_header(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["notifications"]["path"] == "/ws/realtime/notifications/"
    assert payload["notifications"]["profile_id"] == profile.id

    ticket_payload = read_realtime_ticket(payload["notifications"]["ticket"])
    assert ticket_payload is not None
    assert ticket_payload["channel"] == "notifications"
    assert ticket_payload["profile_id"] == profile.id


@pytest.mark.django_db
def test_project_realtime_session_returns_project_and_notification_tickets():
    user = get_user_model().objects.create_user(
        email="manager@example.com",
        password="devpass123",
        username="manager",
        first_name="Manager",
        last_name="User",
        language="it",
    )
    workspace = Workspace.objects.create(name="Project Realtime Workspace")
    profile = Profile.objects.create(
        workspace=workspace,
        user=user,
        email=user.email,
        role=WorkspaceRole.MANAGER,
        first_name="Manager",
        last_name="User",
        language="it",
    )
    token = login_and_get_token(email=user.email, password="devpass123")
    client = Client()

    response = client.get(
        "/api/v1/projects/42/realtime/session",
        **auth_header(token),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["project"]["path"] == "/ws/realtime/projects/42/"
    assert payload["project"]["profile_id"] == profile.id
    assert payload["project"]["project_id"] == 42
    assert payload["notifications"]["profile_id"] == profile.id

    project_ticket_payload = read_realtime_ticket(payload["project"]["ticket"])
    assert project_ticket_payload is not None
    assert project_ticket_payload["channel"] == "project"
    assert project_ticket_payload["project_id"] == 42
