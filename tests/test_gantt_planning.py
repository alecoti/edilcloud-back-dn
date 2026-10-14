from datetime import date, datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.utils import timezone

from edilcloud.modules.projects.gantt_import import parse_gantt_import_file
from edilcloud.modules.projects.gantt_planning import (
    apply_project_schedule_simulation, get_project_planning, planning_risks,
    restore_project_schedule_version, simulate_project_schedule, update_project_schedule_rule,
)
from edilcloud.modules.projects.models import (
    Project, ProjectActivity, ProjectMember, ProjectMemberStatus,
    ProjectScheduleLink, ProjectScheduleVersion, ProjectTask,
)
from edilcloud.modules.projects.models import ProjectSchedulePlan, ProjectPost
from edilcloud.modules.projects.gantt_storage import PrivateScheduleStorage
from edilcloud.modules.projects.services import apply_project_gantt_import, update_task_activity
from edilcloud.modules.workspaces.models import WorkspaceRole
from tests.test_projects_api import auth_headers, create_workspace_profile


def project_fixture():
    _, workspace, profile = create_workspace_profile(email="gantt-professional@example.com", password="devpass123", workspace_name="Gantt QA")
    project = Project.objects.create(workspace=workspace, created_by=profile, name="Vincoli cantiere", date_start=date(2026, 10, 12), date_end=date(2026, 11, 30))
    ProjectMember.objects.create(project=project, profile=profile, role=WorkspaceRole.OWNER, status=ProjectMemberStatus.ACTIVE)
    task = ProjectTask.objects.create(project=project, name="Fondazioni", date_start=date(2026, 10, 12), date_end=date(2026, 10, 12))
    activities = [ProjectActivity.objects.create(task=task, title=name,
                    datetime_start=timezone.make_aware(datetime(2026, 10, 12, 8)),
                    datetime_end=timezone.make_aware(datetime(2026, 10, 12, 17))) for name in ("Scavo", "Getto")]
    ProjectScheduleLink.objects.create(project=project, source_activity=activities[0], target_activity=activities[1], link_type="e2s")
    return profile, project, task, activities


@pytest.mark.django_db
def test_calendar_cpm_simulation_is_read_only_and_application_is_recoverable():
    profile, project, task, activities = project_fixture()
    initial = get_project_planning(profile=profile, project_id=project.id)
    preview = simulate_project_schedule(profile=profile, project_id=project.id, expected_revision=initial["revision"])
    assert preview["can_apply"] is True
    proposal = next(row for row in preview["proposals"] if row["ref"] == f"activity-{activities[1].id}")
    assert proposal["start"] == "2026-10-13T08:00:00"
    assert proposal["end"] == "2026-10-13T17:00:00"
    assert proposal["critical"] is True
    assert proposal["total_slack_minutes"] == 0
    activities[1].refresh_from_db()
    assert timezone.localtime(activities[1].datetime_start).day == 12
    assert ProjectScheduleVersion.objects.count() == 0
    applied = apply_project_schedule_simulation(profile=profile, project_id=project.id, expected_revision=initial["revision"])
    assert applied["revision"] != initial["revision"]
    activities[1].refresh_from_db()
    assert timezone.localtime(activities[1].datetime_start).day == 13
    assert ProjectScheduleVersion.objects.count() == 1
    backup = ProjectScheduleVersion.objects.get()
    restored = restore_project_schedule_version(profile=profile, project_id=project.id, version_id=backup.id, expected_revision=applied["revision"])
    assert [(row["ref"], row["start"], row["end"]) for row in restored["rows"]] == [(row["ref"], row["start"], row["end"]) for row in initial["rows"]]
    assert [(link["source"], link["target"], link["type"]) for link in restored["links"]] == [(link["source"], link["target"], link["type"]) for link in initial["links"]]
    activities[1].refresh_from_db()
    assert timezone.localtime(activities[1].datetime_start).day == 12


@pytest.mark.django_db
def test_must_start_constraint_and_predecessor_conflict_cannot_be_applied():
    profile, project, _, activities = project_fixture()
    current = get_project_planning(profile=profile, project_id=project.id)
    current = update_project_schedule_rule(profile=profile, project_id=project.id, entity_ref=f"activity-{activities[1].id}", expected_revision=current["revision"],
                payload={"constraint_type": "mso", "constraint_date": "2026-10-12T08:00:00", "mode": "auto"})
    result = simulate_project_schedule(profile=profile, project_id=project.id, expected_revision=current["revision"])
    assert result["can_apply"] is False
    assert any(risk["code"] in {"date-constraint-conflict", "dependency-conflict"} for risk in result["risks"])
    with pytest.raises(ValueError, match="conflitti"):
        apply_project_schedule_simulation(profile=profile, project_id=project.id, expected_revision=current["revision"])
    activities[1].refresh_from_db()
    assert timezone.localtime(activities[1].datetime_start).day == 12


@pytest.mark.django_db
def test_stale_plan_and_missing_date_are_rejected_without_versions_or_writes():
    profile, project, task, activities = project_fixture()
    revision = get_project_planning(profile=profile, project_id=project.id)["revision"]
    with pytest.raises(ValueError, match="richiede una data"):
        update_project_schedule_rule(profile=profile, project_id=project.id, entity_ref=f"activity-{activities[1].id}", expected_revision=revision, payload={"constraint_type": "mso"})
    assert not ProjectScheduleVersion.objects.exists()
    task.name = "Piano modificato da un collega"
    task.save()
    with pytest.raises(ValueError, match="cambiato"):
        simulate_project_schedule(profile=profile, project_id=project.id, expected_revision=revision)
    assert not ProjectScheduleVersion.objects.exists()


@pytest.mark.django_db
def test_planning_read_has_no_jvm_and_viewer_cannot_change_rules(monkeypatch):
    profile, project, _, activities = project_fixture()
    monkeypatch.setattr("edilcloud.modules.projects.gantt_planning.subprocess.run", lambda *args, **kwargs: pytest.fail("Planning GET must not start Java"))
    client = Client()
    headers = auth_headers(client, email=profile.email, password="devpass123")
    response = client.get(f"/api/v1/projects/{project.id}/gantt/planning", **headers)
    assert response.status_code == 200
    _, _, worker = create_workspace_profile(email="gantt-worker@example.com", password="devpass123", workspace_name="Subappaltatore")
    worker.role = WorkspaceRole.WORKER
    worker.save()
    ProjectMember.objects.create(project=project, profile=worker, role=WorkspaceRole.WORKER, status=ProjectMemberStatus.ACTIVE)
    headers = auth_headers(client, email=worker.email, password="devpass123")
    response = client.patch(f"/api/v1/projects/{project.id}/gantt/planning/rules/activity-{activities[0].id}",
                            data={"expected_revision": response.json()["revision"], "constraint_type": "asap"}, content_type="application/json", **headers)
    assert response.status_code == 400
    assert not ProjectScheduleVersion.objects.exists()


@pytest.mark.parametrize("constraint, date_field, bound, violates", [
    ("mso", "start", "2026-10-12T08:00:00", False), ("mso", "start", "2026-10-13T08:00:00", True),
    ("mfo", "end", "2026-10-12T17:00:00", False), ("mfo", "end", "2026-10-13T17:00:00", True),
    ("snet", "start", "2026-10-13T08:00:00", True), ("snlt", "start", "2026-10-11T08:00:00", True),
    ("fnet", "end", "2026-10-13T17:00:00", True), ("fnlt", "end", "2026-10-11T17:00:00", True),
    ("asap", "start", None, False), ("alap", "end", None, False),
])
def test_constraint_diagnostics_distinguish_all_project_rules(constraint, date_field, bound, violates):
    row = {"ref": "activity-1", "start": "2026-10-12T08:00:00", "end": "2026-10-12T17:00:00", "constraint_type": constraint, "constraint_date": bound}
    result = planning_risks([row], {})
    assert any(item["code"] == "date-constraint-conflict" for item in result) == violates


def test_deadline_is_a_warning_and_kept_separate_from_date_constraint():
    result = planning_risks([{"ref": "activity-1", "start": "2026-10-12T08:00:00", "end": "2026-10-12T17:00:00", "constraint_type": "asap", "deadline": "2026-10-11T17:00:00"}], {})
    assert len(result) == 1
    assert result[0]["code"] == "deadline-exceeded"
    assert result[0]["severity"] == "warning"
    assert result[0]["evidence"]["delay_minutes"] == 1440


def test_xml_preserves_eight_constraints_ff_zero_fractional_lag_and_subphases():
    task_rows = ['<Task><UID>1</UID><Name>Fase</Name><Summary>1</Summary><OutlineLevel>1</OutlineLevel><Start>2026-10-12T08:00:00</Start><Finish>2026-10-20T17:00:00</Finish></Task>']
    for code in range(8):
        predecessor = '<PredecessorLink><PredecessorUID>2</PredecessorUID><Type>0</Type><LinkLag>-1200</LinkLag><LagFormat>5</LagFormat></PredecessorLink>' if code == 7 else ''
        task_rows.append(f'<Task><UID>{code + 2}</UID><Name>Vincolo {code}</Name><OutlineLevel>2</OutlineLevel><Start>2026-10-12T08:30:00</Start><Finish>2026-10-12T17:00:00</Finish><ConstraintType>{code}</ConstraintType><ConstraintDate>2026-10-12T08:30:00</ConstraintDate><Deadline>2026-10-20T17:00:00</Deadline>{predecessor}</Task>')
    xml = '<Project><MinutesPerDay>480</MinutesPerDay><Tasks>' + ''.join(task_rows) + '</Tasks></Project>'
    plan = parse_gantt_import_file(SimpleUploadedFile("constraints.xml", xml.encode()))
    assert {row.schedule_metadata["constraint_type"] for row in plan.phases[0].activities} == {"asap", "alap", "mso", "mfo", "snet", "snlt", "fnet", "fnlt"}
    assert plan.phases[0].activities[0].schedule_metadata["start"] == "2026-10-12T08:30:00"
    assert plan.links[0].link_type == "e2e"
    assert plan.links[0].schedule_metadata["lag_minutes"] == -120
    assert plan.source_xml == xml


@pytest.mark.django_db
def test_direct_drag_preserves_hard_constraints_and_rolls_back_backup_on_error():
    profile, project, _, activities = project_fixture()
    activity = activities[0]
    current = get_project_planning(profile=profile, project_id=project.id)
    update_project_schedule_rule(profile=profile, project_id=project.id, entity_ref=f"activity-{activity.id}",
                                 expected_revision=current["revision"], payload={"constraint_type": "mso", "constraint_date": "2026-10-12T08:00:00"})
    versions = ProjectScheduleVersion.objects.count()
    with pytest.raises(ValueError, match="vincolo di data"):
        update_task_activity(profile=profile, activity_id=activity.id, title=activity.title,
                             datetime_start=timezone.make_aware(datetime(2026, 10, 13, 8)),
                             datetime_end=timezone.make_aware(datetime(2026, 10, 13, 17)))
    activity.refresh_from_db()
    assert timezone.localtime(activity.datetime_start).day == 12
    assert ProjectScheduleVersion.objects.count() == versions


@pytest.mark.django_db
def test_direct_drag_of_automatic_task_adds_snet_without_moving_other_tasks():
    profile, project, _, activities = project_fixture()
    ProjectSchedulePlan.objects.create(project=project)
    update_task_activity(profile=profile, activity_id=activities[1].id, title=activities[1].title,
                         datetime_start=timezone.make_aware(datetime(2026, 10, 14, 8)),
                         datetime_end=timezone.make_aware(datetime(2026, 10, 14, 17)))
    activities[1].refresh_from_db()
    assert activities[1].schedule_metadata["constraint_type"] == "snet"
    assert activities[1].schedule_metadata["constraint_date"] == "2026-10-14T08:00:00"
    activities[0].refresh_from_db()
    assert timezone.localtime(activities[0].datetime_start).day == 12
    assert ProjectScheduleVersion.objects.count() == 1


@pytest.mark.django_db
def test_original_mpp_is_byte_exact_private_and_download_requires_project_permission(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path
    profile, project, _, _ = project_fixture()
    storage = PrivateScheduleStorage(location=tmp_path / "private")
    monkeypatch.setattr(ProjectSchedulePlan._meta.get_field("original_file"), "storage", storage)
    source = (Path(__file__).parent / "data/sample-ms-project-task-links.mpp").read_bytes()
    apply_project_gantt_import(profile=profile, project_id=project.id,
                              uploaded_file=SimpleUploadedFile("plan.mpp", source), replace_existing=True)
    plan = ProjectSchedulePlan.objects.get(project=project)
    assert plan.source_sha256 == hashlib.sha256(source).hexdigest()
    with plan.original_file.open("rb") as original:
        assert original.read() == source
    assert plan.metadata["entity_map"]
    with pytest.raises(ValueError, match="autenticato"):
        _ = plan.original_file.url
    client = Client()
    headers = auth_headers(client, email=profile.email, password="devpass123")
    response = client.get(f"/api/v1/projects/{project.id}/gantt/planning/source", **headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == source
    assert response["Cache-Control"] == "private, no-store"
    _, _, other = create_workspace_profile(email="outside-gantt@example.com", password="devpass123", workspace_name="Altro cantiere")
    headers = auth_headers(client, email=other.email, password="devpass123")
    assert client.get(f"/api/v1/projects/{project.id}/gantt/planning/source", **headers).status_code == 404
    # Deleting an imported operational row must not revive it silently as a source-only task.
    imported_task = project.tasks.first()
    imported_task.delete()
    current = get_project_planning(profile=profile, project_id=project.id)
    assert current["can_simulate"] is False
    assert any(item["code"] == "operational-entity-removed" for item in current["risks"])


@pytest.mark.django_db
def test_replace_import_cannot_cascade_away_operational_posts():
    from pathlib import Path
    profile, project, task, activities = project_fixture()
    post = ProjectPost.objects.create(project=project, task=task, activity=activities[0], author=profile, text="Getto registrato")
    source = (Path(__file__).parent / "data/sample-ms-project-task-links.mpp").read_bytes()
    with pytest.raises(ValueError, match="lavoro già registrato"):
        apply_project_gantt_import(profile=profile, project_id=project.id,
                                  uploaded_file=SimpleUploadedFile("plan.mpp", source), replace_existing=True)
    assert ProjectPost.objects.filter(id=post.id).exists()
    assert ProjectTask.objects.filter(id=task.id).exists()
    assert not ProjectScheduleVersion.objects.exists()
