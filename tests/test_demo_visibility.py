import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from edilcloud.modules.projects import demo_master_admin
from edilcloud.modules.notifications.models import Notification
from edilcloud.modules.notifications.services import visible_notifications_queryset
from edilcloud.modules.projects.models import Project, ProjectMember, ProjectPost
from edilcloud.modules.projects.services import (
    accessible_feed_posts_queryset,
    list_projects,
    serialize_project_summary,
)
from edilcloud.modules.search.services import search_workspace_index
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole
from edilcloud.modules.workspaces.services import serialize_current_workspace_profile


@pytest.fixture
def demo_profiles(db, monkeypatch):
    user = get_user_model().objects.create_user(
        username="demo-visibility", email="demo-visibility@example.invalid", password="testpass123",
    )
    profiles = [Profile.objects.create(
        user=user, email=user.email, workspace=Workspace.objects.create(name=f"Visibility {index}"),
        role=WorkspaceRole.OWNER,
    ) for index in range(2)]
    demo = Project.objects.create(
        workspace=profiles[0].workspace, created_by=profiles[0],
        name="Demonstration visibility", date_start="2026-10-01", is_demo_master=True,
    )
    for profile in profiles:
        ProjectMember.objects.create(project=demo, profile=profile, role=WorkspaceRole.MANAGER)
    ProjectPost.objects.create(project=demo, author=profiles[0], text="Demo update")
    real = Project.objects.create(
        workspace=profiles[0].workspace, created_by=profiles[0],
        name="Real project", date_start="2026-10-01",
    )
    ProjectMember.objects.create(project=real, profile=profiles[0], role=WorkspaceRole.OWNER)
    monkeypatch.setattr(demo_master_admin, "get_demo_master_project", lambda: demo)
    monkeypatch.setattr(demo_master_admin, "ensure_demo_master_assistant_assets", lambda _project: None)
    return profiles, demo, real


def test_demo_visibility_is_personal_persistent_and_reversible(demo_profiles):
    profiles, demo, real = demo_profiles
    first, second = profiles
    membership_ids = list(ProjectMember.objects.filter(project=demo).values_list("id", flat=True))
    result = demo_master_admin.set_demo_project_visibility(profile=first, visible=False)
    first.refresh_from_db()
    second.refresh_from_db()
    assert result == {"visible": False, "project": None}
    assert first.demo_project_hidden is True
    assert second.demo_project_hidden is False
    assert serialize_current_workspace_profile(first)["demo_project_hidden"] is True
    assert [item["id"] for item in list_projects(profile=first)] == [real.id]
    assert [item["id"] for item in list_projects(profile=second)] == [demo.id]
    assert not accessible_feed_posts_queryset(profile=first).exists()
    assert accessible_feed_posts_queryset(profile=second).exists()
    assert demo_master_admin.ensure_demo_master_project_for_profile(profile=first) is None
    assert list(ProjectMember.objects.filter(project=demo).values_list("id", flat=True)) == membership_ids
    restored = demo_master_admin.set_demo_project_visibility(profile=first, visible=True)
    first.refresh_from_db()
    assert restored["project"]["is_demo_master"] is True
    assert first.demo_project_hidden is False
    assert {item["id"] for item in list_projects(profile=first)} == {demo.id, real.id}
    assert Project.objects.filter(pk=demo.pk).exists()


def test_hidden_demo_is_absent_from_search_but_real_projects_remain(demo_profiles):
    profiles, demo, real = demo_profiles
    first = profiles[0]
    claims = {"profile_id": first.id}
    visible = search_workspace_index(user=first.user, claims=claims, query="Demonstration")
    assert visible["sections"]["projects"][0]["is_demo_master"] is True
    demo_master_admin.set_demo_project_visibility(profile=first, visible=False)
    result = search_workspace_index(user=first.user, claims=claims, query="Demonstration")
    assert result["total"] == 0
    result = search_workspace_index(user=first.user, claims=claims, query="Real project")
    assert result["sections"]["projects"][0]["id"] == f"project:{real.id}"
    assert serialize_project_summary(demo)["is_demo_master"] is True
    assert serialize_project_summary(real)["is_demo_master"] is False


def test_hidden_demo_notifications_are_not_counted_or_marked_read(demo_profiles):
    profiles, demo, real = demo_profiles
    first, second = profiles
    demo_notice = Notification.objects.create(recipient_profile=first, project_id=demo.id, subject="Demo")
    real_notice = Notification.objects.create(recipient_profile=first, project_id=real.id, subject="Real")
    other_notice = Notification.objects.create(recipient_profile=second, project_id=demo.id, subject="Other profile")
    demo_master_admin.set_demo_project_visibility(profile=first, visible=False)
    first.refresh_from_db()
    assert list(visible_notifications_queryset(first).values_list("id", flat=True)) == [real_notice.id]
    assert list(visible_notifications_queryset(second).values_list("id", flat=True)) == [other_notice.id]
    demo_master_admin.set_demo_project_visibility(profile=first, visible=True)
    first.refresh_from_db()
    assert {item.id for item in visible_notifications_queryset(first)} == {demo_notice.id, real_notice.id}
    assert Notification.objects.filter(pk=demo_notice.pk, read_at__isnull=True).exists()


def test_visibility_endpoint_requires_authentication_and_only_changes_active_profile(demo_profiles):
    profiles, _demo, _real = demo_profiles
    client = Client()
    response = client.patch("/api/v1/projects/demo-master/visibility", data=json.dumps({"visible": False}), content_type="application/json")
    assert response.status_code == 401
    login = client.post("/api/v1/auth/login", data=json.dumps({"username_or_email": profiles[0].email, "password": "testpass123"}), content_type="application/json")
    assert login.status_code == 200
    auth = {"HTTP_AUTHORIZATION": f"JWT {login.json()['token']}"}
    active_id = login.json()["extra"]["profile"]["id"]
    response = client.patch("/api/v1/projects/demo-master/visibility", data=json.dumps({"visible": False, "profile_id": profiles[1].id}), content_type="application/json", **auth)
    assert response.status_code == 200
    for profile in profiles:
        profile.refresh_from_db()
        assert profile.demo_project_hidden is (profile.id == active_id)
    response = client.post("/api/v1/projects/demo-master/provision", **auth)
    assert response.status_code == 200
    assert response.json() is None
