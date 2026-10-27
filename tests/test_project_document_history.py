"""Private document metadata follows its ACL in history, cursors and ZIP JSON."""

from datetime import timedelta
from io import BytesIO
import json
import zipfile

from django.utils import timezone
import pytest

from edilcloud.modules.elaborati.models import ElaboratoOwnership
from edilcloud.modules.projects.archive import export_project_archive
from edilcloud.modules.projects.models import ProjectOperationalEvent, ProjectMember
from edilcloud.modules.projects.operational_history import list_project_operational_timeline
from tests import test_notifications_document_scope as fixtures

site = fixtures.site
issued = fixtures.issued
pytestmark = pytest.mark.django_db


def history_event(site, issued, *, private=True, **overrides):
    revision, document, _ = issued
    now = timezone.now()
    payload = {
        "projectId": site[0].pk,
        "documentId": document.pk if private else None,
        "data": {"elaborato_revision_id": str(revision.pk)} if private else {},
        "timeline": {
            "id": str(now.timestamp()),
            "description": "PRIVATE-DOCUMENT-QA" if private else "Public post",
            "target_document_id": document.pk if private else None,
        },
    }
    values = dict(
        project=site[0],
        event_type="document.created" if private else "post.created",
        document_id_snapshot=document.pk if private else None,
        occurred_at=now,
        payload=payload,
    )
    values.update(overrides)
    return ProjectOperationalEvent.objects.create(**values)


def timeline(site, profile, **kwargs):
    return list_project_operational_timeline(
        profile=profile, project_id=site[0].pk, mode="phase", task_id=1, **kwargs
    )


def private_events(page):
    return [event for event in page["events"] if event.get("target_document_id")]


def test_company_legacy_alias_and_revocation(site, issued):
    history_event(site, issued)
    for profile, expected in [(site[1], 1), (site[2], 1), (site[3], 0), (issued[2], 0)]:
        page = timeline(site, profile)
        assert len(private_events(page)) == expected
        assert any(event.get("target_post_id") == site[4].pk for event in page["events"])
    ElaboratoOwnership.objects.filter(document=issued[0].elaborato).delete()
    assert len(private_events(timeline(site, site[1]))) == 1
    assert private_events(timeline(site, site[2])) == []
    ProjectMember.objects.filter(project=site[0], profile=site[1]).update(disabled=True)
    assert timeline(site, site[1])["events"] == []


def test_filter_precedes_page_and_cursor_captures_profile_and_company(site, issued):
    first = history_event(site, issued, private=False)
    history_event(site, issued)
    last = history_event(
        site, issued, private=False, occurred_at=timezone.now() + timedelta(seconds=1)
    )
    page = timeline(site, site[3], limit=1)
    assert [r["id"] for r in page["events"]] == [last.payload["timeline"]["id"]]
    assert page["has_more"]
    second = timeline(site, site[3], limit=1, cursor=page["next_cursor"])
    assert [r["id"] for r in second["events"]] == [first.payload["timeline"]["id"]]
    assert second["has_more"]
    third = timeline(site, site[3], limit=1, cursor=second["next_cursor"])
    assert third["events"][0]["target_post_id"] == site[4].pk
    assert not third["has_more"] and third["next_cursor"] is None
    with pytest.raises(ValueError):
        timeline(site, site[2], limit=1, cursor=page["next_cursor"])


@pytest.mark.parametrize(
    "case", ["bad_marker", "wrong_target", "wrong_project", "orphan", "malformed_id"]
)
def test_inconsistent_historical_targets_fail_closed(site, issued, case):
    event = history_event(site, issued)
    if case == "bad_marker":
        event.payload["data"]["elaborato_revision_id"] = {"bad": True}
    elif case == "wrong_target":
        event.payload["documentId"] = 987654
    elif case == "wrong_project":
        event.payload["projectId"] = 987654
    elif case == "malformed_id":
        event.payload["documentId"] = "999999999999999999999999999999999999999"
    else:
        event.payload["data"] = {}
        issued[0].drive_document = None
        issued[0].save(update_fields=("drive_document",))
    event.save()
    assert private_events(timeline(site, site[1])) == []


def test_missing_snapshot_uses_existing_authoritative_drive_target(site, issued):
    event = history_event(site, issued, document_id_snapshot=None)
    assert len(private_events(timeline(site, site[2]))) == 1
    assert private_events(timeline(site, site[3])) == []
    assert ProjectOperationalEvent.objects.get(pk=event.pk).document_id_snapshot is None


def test_archive_json_and_manifest_do_not_include_other_company_private_metadata(site, issued):
    history_event(site, issued)
    history_event(site, issued, private=False)
    response = export_project_archive(profile=site[3], project_id=site[0].pk)
    try:
        archive = zipfile.ZipFile(BytesIO(b"".join(response.streaming_content)))
        for name in archive.namelist():
            if name.endswith(".json"):
                assert b"PRIVATE-DOCUMENT-QA" not in archive.read(name), name
        manifest = json.loads(archive.read("manifest/project.json"))
        assert manifest["visibility"] == {
            "scope": "authorized_view",
            "profile_id": site[3].pk,
            "workspace_id": site[3].workspace_id,
        }
        events = json.loads(archive.read("operations/events.json"))
        assert not any(e["document_id_snapshot"] == issued[1].pk for e in events)
        reconstructed = json.loads(archive.read("operations/timeline.json"))
        assert any(
            event.get("source") == "derived" and event.get("target_post_id") == site[4].pk
            for event in reconstructed
        )
        contents = json.loads(archive.read("manifest/contents.json"))
        assert contents["timeline_events"] == len(reconstructed)
    finally:
        response.close()


def test_legacy_post_without_audit_projection_remains_in_timeline(site):
    """Release criterion: switching to authoritative history must retain legacy posts."""
    from datetime import date
    from edilcloud.modules.projects.models import ProjectTask

    project, owner, _, _, post = site
    task = ProjectTask.objects.create(
        project=project, name="Legacy phase QA", date_start=date.today(), date_end=date.today()
    )
    post.task = task
    post.save(update_fields=("task",))
    # The legacy fixture already has post.created without a timeline projection.
    page = list_project_operational_timeline(
        profile=owner, project_id=project.pk, mode="phase", task_id=task.pk, limit=40
    )
    assert any(event.get("target_post_id") == post.pk for event in page["events"])
