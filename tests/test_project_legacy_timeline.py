"""Legacy reconstruction, audit preference and mixed-source cursor invariants."""

from datetime import date, timedelta
import hashlib
from pathlib import Path

from django.core import signing
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
import pytest

from edilcloud.modules.projects.models import (
    PostComment,
    ProjectActivity,
    ProjectMember,
    ProjectOperationalEvent,
    ProjectTask,
)
from edilcloud.modules.projects.operational_history import (
    list_project_operational_timeline,
    persist_project_operational_event,
)
from tests import test_elaborati as baseline

site = baseline.site
pytestmark = pytest.mark.django_db


@pytest.fixture
def source(site):
    project, owner, _, _, post = site
    task = ProjectTask.objects.create(
        project=project, name="Legacy phase", date_start=date.today(), date_end=date.today()
    )
    post.task = task
    post.save(update_fields=("task",))
    return task, post


def read(site, source, **kwargs):
    return list_project_operational_timeline(
        profile=site[1], project_id=site[0].pk, mode="phase", task_id=source[0].pk, **kwargs
    )


def record_audit(site, source, *, kind="post.created", at=None, private=False):
    task, post = source
    payload = {
        "eventId": "audit-known",
        "type": kind,
        "timestamp": (at or post.published_date).isoformat(),
        "projectId": site[0].pk,
        "taskId": task.pk,
        "postId": post.pk,
        "profileId": site[1].pk,
        "data": {"post_kind": post.post_kind, "excerpt": "Recorded audit content"},
    }
    if private:
        payload["data"]["elaborato_revision_id"] = "00000000-0000-0000-0000-000000000000"
    persist_project_operational_event(project_id=site[0].pk, payload=payload)


def test_legacy_read_has_provenance_author_and_no_database_writes(site, source):
    before = ProjectOperationalEvent.objects.count()
    with CaptureQueriesContext(connection) as queries:
        page = read(site, source, limit=40)
    assert len(page["events"]) == 1
    event = page["events"][0]
    assert event["source"] == "derived" and event["actor"]["profile_id"] == site[1].pk
    assert event["actor"]["company_name"] is None
    assert event["reconstruction"] == {
        "record_type": "post",
        "record_id": source[1].pk,
        "timestamp_field": "published_date",
        "content_basis": "current_record",
        "actor_basis": "record_author",
    }
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries
    )
    assert ProjectOperationalEvent.objects.count() == before


def test_audit_creation_wins_and_is_not_reconstructed_for_other_company(site, source):
    record_audit(site, source)
    events = read(site, source)["events"]
    assert len(events) == 1 and events[0]["source"] == "audit"
    assert events[0]["description"] == "Recorded audit content"
    ProjectOperationalEvent.objects.filter(payload__eventId="audit-known").delete()
    record_audit(site, source, private=True)
    # A denied authoritative event must not reappear via the legacy fallback.
    assert read(site, source)["events"] == []


def test_last_edit_does_not_invent_an_editor_or_issue_resolution(site, source):
    _, post = source
    post.post_kind = "issue"
    post.alert = False
    post.edited_at = post.published_date + timedelta(hours=1)
    post.save(update_fields=("post_kind", "alert", "edited_at"))
    events = read(site, source)["events"]
    updated = next(e for e in events if e["event_kind"] == "post_updated")
    assert updated["actor"]["profile_id"] is None
    assert updated["actor"]["name"] == "Autore modifica non registrato"
    assert not any(e["event_kind"] == "issue_resolved" for e in events)
    assert updated["reconstruction"]["timestamp_field"] == "edited_at"


def test_latest_audit_update_suppresses_only_covered_last_edit(site, source):
    _, post = source
    earlier = post.published_date + timedelta(hours=1)
    post.edited_at = earlier + timedelta(hours=1)
    post.save(update_fields=("edited_at",))
    record_audit(site, source, kind="post.updated", at=earlier)
    assert len([e for e in read(site, source)["events"] if e["event_kind"] == "post_updated"]) == 2
    record_audit(site, source, kind="post.updated", at=post.edited_at)
    assert not any(
        e["source"] == "derived" and e["event_kind"] == "post_updated"
        for e in read(site, source)["events"]
    )


def test_deleted_content_is_not_reintroduced_from_current_records(site, source):
    _, post = source
    post.text = "OLD TEXT MUST NOT REAPPEAR"
    post.is_deleted = True
    post.deleted_at = post.published_date + timedelta(hours=1)
    post.save(update_fields=("text", "is_deleted", "deleted_at"))
    events = read(site, source)["events"]
    assert len(events) == 2 and any(e["event_kind"] == "post_deleted" for e in events)
    assert "OLD TEXT MUST NOT REAPPEAR" not in str(events)


@pytest.mark.parametrize("state", ["created", "edited", "deleted"])
def test_comment_replies_preserve_last_known_state_and_actor_limits(site, source, state):
    _, post = source
    comment = PostComment.objects.create(post=post, author=site[2], text="Legacy comment")
    reply = PostComment.objects.create(
        post=post, author=site[1], parent=comment, text="Legacy reply"
    )
    if state != "created":
        comment.edited_at = comment.created_at + timedelta(hours=1)
    if state == "deleted":
        comment.is_deleted = True
        comment.deleted_at = comment.created_at + timedelta(hours=2)
    comment.save()
    events = read(site, source)["events"]
    comments = [e for e in events if e.get("target_comment_id") == comment.pk]
    assert len(comments) == 1
    event = comments[0]
    assert (
        event["event_kind"]
        == {"created": "comment_added", "edited": "comment_updated", "deleted": "comment_deleted"}[
            state
        ]
    )
    assert event["actor"]["profile_id"] == (site[2].pk if state == "created" else None)
    assert any(e.get("target_comment_id") == reply.pk for e in events)


def test_one_item_pages_have_no_gaps_with_equal_times_and_colliding_source_ids(site, source):
    _, post = source
    comment = PostComment.objects.create(
        id=post.pk, post=post, author=site[2], text="Same timestamp"
    )
    PostComment.objects.filter(pk=comment.pk).update(created_at=post.published_date)
    ProjectOperationalEvent.objects.create(
        id=post.pk + 1000,
        project=site[0],
        event_type="task.updated",
        task_id_snapshot=source[0].pk,
        occurred_at=post.published_date,
        payload={"timeline": {"id": "independent-audit", "label": "Recorded"}},
    )
    expected = [e["id"] for e in read(site, source)["events"]]
    assert len(expected) == 3
    found = []
    cursor = None
    for _ in range(4):
        page = read(site, source, limit=1, cursor=cursor)
        found.extend(e["id"] for e in page["events"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert found == expected and len(set(found)) == 3
    key = signing.loads(cursor, salt="edilcloud-read-window-v1")
    assert key["origin"] in {"audit", "post", "comment"}
    key["kind"] = True
    with pytest.raises(ValueError):
        read(site, source, limit=1, cursor=signing.dumps(key, salt="edilcloud-read-window-v1"))


def test_general_phase_activity_and_revocation_use_same_scope_for_legacy(site, source):
    task, post = source
    activity = ProjectActivity.objects.create(
        task=task,
        title="Legacy activity",
        datetime_start=timezone.now(),
        datetime_end=timezone.now() + timedelta(hours=1),
    )
    type(post).objects.create(project=site[0], activity=activity, author=site[1], text="Activity")

    def scoped(mode):
        return list_project_operational_timeline(
            profile=site[1],
            project_id=site[0].pk,
            mode=mode,
            task_id=task.pk,
            activity_id=activity.pk if mode == "activity" else None,
        )["events"]

    assert (
        len(scoped("phase")) == 2 and len(scoped("general")) == 1 and len(scoped("activity")) == 1
    )
    ProjectMember.objects.filter(profile=site[1], project=site[0]).update(disabled=True)
    assert scoped("phase") == []


def test_sql_policy_copies_match_exactly():
    root = Path(__file__).resolve().parents[2]
    source = (
        Path(__file__).resolve().parents[1] / "src/edilcloud/modules/projects/legacy_history.sql"
    )
    native_root = root / "edilcloud-back-rust"
    if not native_root.is_dir():
        native_root = root / "rust"
    native = native_root / "resources/projects/legacy_history.sql"
    if not native.exists():
        pytest.skip("Cross-backend SQL contract requires the sibling Rust checkout")
    assert (
        hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(native.read_bytes()).digest()
    )
