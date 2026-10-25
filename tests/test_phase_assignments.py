import json
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from edilcloud.modules.identity.services import issue_authenticated_response
from edilcloud.modules.projects.assignments import assignment_state, update_assignment
from edilcloud.modules.projects.models import Project, ProjectActivity, ProjectMember, ProjectMemberStatus, ProjectTask
from edilcloud.modules.projects.services import create_task_activity, update_task_activity
from edilcloud.modules.workspaces.models import Profile, Workspace


@pytest.fixture
def site(db):
    owner_company = Workspace.objects.create(name="Proprietaria")
    contractor = Workspace.objects.create(name="XXX SPA")
    foreign_company = Workspace.objects.create(name="Non invitata")
    people = {}
    for label, company, role, first, last in [
        ("owner", owner_company, "o", "Owner", "Progetto"),
        ("admin", contractor, "o", "Owner", "Impresa"),
        ("delegate", contractor, "d", "Delegate", "Impresa"),
        ("manager", contractor, "m", "Manager", "Impresa"),
        ("carlo", contractor, "w", "Carlo", "Piscopo"),
        ("gennaro", contractor, "w", "Gennaro", "Cassese"),
        ("foreign", foreign_company, "o", "Altra", "Persona"),
    ]:
        user = get_user_model().objects.create_user(email=f"{label}@assignment.invalid", password="test-password")
        people[label] = Profile.objects.create(user=user, workspace=company, role=role,
            email=user.email, first_name=first, last_name=last)
    project = Project.objects.create(name="Cantiere", workspace=owner_company,
        created_by=people["owner"], date_start=date(2026, 10, 1), date_end=date(2026, 11, 1))
    for label in ("owner", "manager", "carlo"):
        ProjectMember.objects.create(project=project, profile=people[label], role="o" if label == "owner" else "w")
    task = ProjectTask.objects.create(project=project, name="Fase", date_start=project.date_start, date_end=project.date_end)
    start = timezone.now()
    children = [ProjectActivity.objects.create(task=task, title=f"Sottofase {i}", datetime_start=start,
        datetime_end=start + timedelta(hours=1)) for i in range(2)]
    return project, task, children, people, contractor, foreign_company


def assign_company(site):
    _, task, _, people, contractor, _ = site
    return update_assignment(profile=people["owner"], task_id=task.id, company_id=contractor.id, set_company=True)


@pytest.mark.django_db
def test_owner_assigns_company_and_its_admins_can_enter(site):
    project, task, _, people, contractor, _ = site
    result = assign_company(site)
    assert result["assigned_company"]["id"] == contractor.id
    for label in ("admin", "delegate"):
        membership = ProjectMember.objects.get(project=project, profile=people[label])
        assert membership.status == ProjectMemberStatus.ACTIVE
        assert membership.role == "w"  # no global project privileges granted
    from edilcloud.modules.notifications.models import Notification
    assert Notification.objects.filter(recipient_profile=people["admin"], kind="project.task.assigned").exists()
    assert assignment_state(profile=people["admin"], task_id=task.id)["can_assign_people"] is True


@pytest.mark.django_db
def test_directory_combines_members_and_internal_people_only_and_searches_names(site):
    _, task, _, people, _, _ = site
    assign_company(site)
    state = assignment_state(profile=people["admin"], task_id=task.id)
    directory = {entry["profile"]["id"]: entry["in_project"] for entry in state["people"]}
    assert directory[people["carlo"].id] is True
    assert directory[people["gennaro"].id] is False
    assert people["foreign"].id not in directory
    assert people["owner"].id not in directory
    found = assignment_state(profile=people["admin"], task_id=task.id, query="Gennaro Cassese")
    assert [item["profile"]["id"] for item in found["people"]] == [people["gennaro"].id]


@pytest.mark.django_db
def test_assignment_auto_adds_internal_people_and_children_inherit_with_local_override(site):
    project, task, children, people, _, _ = site
    assign_company(site)
    ids = [people["carlo"].id, people["gennaro"].id]
    update_assignment(profile=people["admin"], task_id=task.id, worker_ids=ids)
    assert ProjectMember.objects.get(project=project, profile=people["gennaro"]).status == ProjectMemberStatus.ACTIVE
    for child in children:
        assert set(child.workers.values_list("id", flat=True)) == set(ids)
    update_assignment(profile=people["delegate"], task_id=task.id, activity_id=children[0].id,
        worker_ids=[people["carlo"].id], inherit_workers=False)
    update_assignment(profile=people["admin"], task_id=task.id, worker_ids=[people["gennaro"].id])
    assert list(children[0].workers.values_list("id", flat=True)) == [people["carlo"].id]
    assert list(children[1].workers.values_list("id", flat=True)) == [people["gennaro"].id]
    assert set(task.workers.values_list("id", flat=True)) == {people["gennaro"].id}
    update_assignment(profile=people["admin"], task_id=task.id, activity_id=children[0].id, inherit_workers=True)
    children[0].refresh_from_db()
    assert children[0].inherit_workers is True
    assert list(children[0].workers.values_list("id", flat=True)) == [people["gennaro"].id]


@pytest.mark.django_db
def test_new_activity_inherits_and_metadata_edits_preserve_inheritance(site):
    _, task, _, people, _, _ = site
    assign_company(site)
    update_assignment(profile=people["admin"], task_id=task.id, worker_ids=[people["carlo"].id])
    start = timezone.now()
    activity = create_task_activity(profile=people["owner"], task_id=task.id, title="Nuova",
        datetime_start=start, datetime_end=start + timedelta(hours=1))
    child = ProjectActivity.objects.get(id=activity["id"])
    assert child.inherit_workers and list(child.workers.values_list("id", flat=True)) == [people["carlo"].id]
    update_task_activity(profile=people["owner"], activity_id=child.id, title="Modificata",
        datetime_start=start, datetime_end=start + timedelta(hours=1))
    child.refresh_from_db()
    assert child.inherit_workers and child.workers.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("actor", ["owner", "manager", "carlo"])
def test_only_assigned_company_owner_delegate_can_assign_people_even_via_http(site, actor):
    _, task, _, people, _, _ = site
    assign_company(site)
    token = issue_authenticated_response(people[actor].user, profile_id=people[actor].id)["token"]
    response = Client().patch(f"/api/v1/tasks/{task.id}/assignment", data=json.dumps({
        "worker_profile_ids": [people["gennaro"].id]}), content_type="application/json", HTTP_AUTHORIZATION=f"JWT {token}")
    assert response.status_code == 403
    assert task.workers.count() == 0


@pytest.mark.django_db
def test_cross_company_and_disabled_people_are_rejected_atomically(site):
    project, task, _, people, _, _ = site
    assign_company(site)
    from ninja.errors import HttpError
    with pytest.raises(HttpError):
        update_assignment(profile=people["admin"], task_id=task.id,
            worker_ids=[people["gennaro"].id, people["foreign"].id])
    assert not ProjectMember.objects.filter(project=project, profile=people["gennaro"]).exists()
    ProjectMember.objects.create(project=project, profile=people["gennaro"], disabled=True)
    with pytest.raises(HttpError):
        update_assignment(profile=people["admin"], task_id=task.id, worker_ids=[people["gennaro"].id])
    assert task.workers.count() == 0


@pytest.mark.django_db
def test_company_change_clears_phase_and_overrides_and_only_owner_can_do_it(site):
    project, task, children, people, _, foreign = site
    assign_company(site)
    update_assignment(profile=people["admin"], task_id=task.id, worker_ids=[people["carlo"].id])
    update_assignment(profile=people["admin"], task_id=task.id, activity_id=children[0].id, worker_ids=[], inherit_workers=False)
    from ninja.errors import HttpError
    with pytest.raises(HttpError):
        update_assignment(profile=people["admin"], task_id=task.id, company_id=None, set_company=True)
    with pytest.raises(HttpError):
        update_assignment(profile=people["owner"], task_id=task.id, company_id=foreign.id, set_company=True)
    update_assignment(profile=people["owner"], task_id=task.id, company_id=project.workspace_id, set_company=True)
    assert task.workers.count() == 0
    for child in children:
        child.refresh_from_db()
        assert child.inherit_workers and child.workers.count() == 0
