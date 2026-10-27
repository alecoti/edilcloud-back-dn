"""Same project, different companies: issued documents are not project-wide news."""

from copy import deepcopy
import uuid

import pytest

from edilcloud.modules.elaborati.models import ElaboratoOwnership
from edilcloud.modules.notifications.document_access import (
    visible_document_notifications,
    notification_delivery_allowed,
)
from edilcloud.modules.notifications.models import Notification, NotificationPushJob
from edilcloud.modules.notifications.services import (
    list_notifications,
    mark_notification_read,
    mark_notifications_read,
)
from edilcloud.modules.projects.models import ProjectDocument, ProjectMember
from edilcloud.modules.workspaces.models import Profile, Workspace
from edilcloud.platform.realtime.access import document_event_allowed
from tests import test_elaborati as baseline

pytestmark = pytest.mark.django_db
site = baseline.site


@pytest.fixture
def issued(site):
    project, owner, worker, other, _ = site
    ProjectMember.objects.create(project=project, profile=other, role="w")
    alias = Profile.objects.create(
        workspace=Workspace.objects.create(name="Alias company"),
        user=owner.user,
        email=owner.email,
        first_name="Alias",
        role="o",
    )
    ProjectMember.objects.create(project=project, profile=alias, role="o")
    revision = baseline.create(site)
    document = ProjectDocument.objects.create(
        project=project,
        uploaded_by=owner,
        title="Reserved issued QA",
        document=f"elaborati/publications/{revision.pk.hex}-{uuid.uuid4().hex}.pdf",
        file_size=5,
    )
    revision.state = "published"
    revision.drive_document = document
    revision.pdf_hash = "a" * 64
    revision.save()
    return revision, document, alias


def notice(profile, revision, document, **changes):
    values = dict(
        recipient_profile=profile,
        subject="PRIVATE QA TITLE",
        kind="project.document.created",
        project_id=document.project_id,
        document_id=document.pk,
        content_type="document",
        object_id=document.pk,
        data={"elaborato_revision_id": str(revision.pk)},
    )
    values.update(changes)
    return Notification.objects.create(**values)


def visible(profile):
    return visible_document_notifications(
        Notification.objects.filter(recipient_profile=profile), profile=profile
    )


@pytest.mark.parametrize("marked", [False, True])
def test_company_and_exact_legacy_creator_control_historical_notices(site, issued, marked):
    revision, document, alias = issued
    owner, worker, other = site[1:4]
    for profile in (owner, worker, other, alias):
        notice(
            profile,
            revision,
            document,
            data={"elaborato_revision_id": str(revision.pk)} if marked else {},
        )
    assert [visible(p).count() for p in (owner, worker, other, alias)] == [1, 1, 0, 0]
    ElaboratoOwnership.objects.filter(document_id=revision.elaborato_id).delete()
    assert [visible(p).count() for p in (owner, worker, other, alias)] == [1, 0, 0, 0]


@pytest.mark.parametrize(
    "problem",
    [
        "bad_marker",
        "wrong_revision",
        "draft",
        "inactive_member",
        "inactive_workspace",
        "missing_target",
        "orphan_private",
        "wrong_project",
    ],
)
def test_ambiguous_or_revoked_document_notices_are_not_delivered(site, issued, problem):
    revision, document, _ = issued
    item = notice(site[2], revision, document)
    if problem == "bad_marker":
        item.data = {"elaborato_revision_id": {"unexpected": "value"}}
    elif problem == "wrong_revision":
        item.data = {"elaborato_revision_id": str(uuid.uuid4())}
    elif problem == "draft":
        revision.state = "draft"
        revision.save(update_fields=("state",))
    elif problem == "inactive_member":
        ProjectMember.objects.filter(profile=site[2], project=site[0]).update(disabled=True)
    elif problem == "inactive_workspace":
        Workspace.objects.filter(pk=site[2].workspace_id).update(is_active=False)
    elif problem == "missing_target":
        item.document_id = 987654
        item.object_id = 987654
        item.data = {}
    elif problem == "orphan_private":
        revision.drive_document = None
        revision.save(update_fields=("drive_document",))
        item.data = {}
    elif problem == "wrong_project":
        item.project_id = 987654
    item.save()
    assert not visible(site[2]).exists()
    assert not notification_delivery_allowed(item)


def test_filter_precedes_pagination_counts_single_and_batch_read(site, issued):
    revision, document, _ = issued
    other = site[3]
    ordinary = ProjectDocument.objects.create(
        project=site[0], document="projects/qa/ordinary.pdf", title="Normal QA", file_size=5
    )
    public = notice(other, revision, ordinary, data={}, subject="ORDINARY QA")
    private = [notice(other, revision, document) for _ in range(4)]
    report = list_notifications(user=other.user, claims={"main_profile": other.pk}, limit=1)
    assert report["unread_count"] == 1 and [v["id"] for v in report["results"]] == [public.pk]
    assert not report["has_more"]
    with pytest.raises(ValueError, match="Notifica non trovata"):
        mark_notification_read(
            user=other.user, claims={"main_profile": other.pk}, notification_id=private[0].pk
        )
    batch = mark_notifications_read(
        user=other.user,
        claims={"main_profile": other.pk},
        notification_ids=[public.pk, *[p.pk for p in private]],
    )
    assert [v["id"] for v in batch["results"]] == [public.pk]
    assert (
        Notification.objects.filter(pk__in=[p.pk for p in private], read_at__isnull=True).count()
        == 4
    )


def test_project_socket_filters_private_payload_but_keeps_ordinary_project_events(site, issued):
    revision, document, alias = issued
    event = {
        "channel": "project",
        "type": "document.created",
        "projectId": site[0].pk,
        "documentId": document.pk,
        "data": {"elaborato_revision_id": str(revision.pk)},
    }
    assert [
        document_event_allowed(profile=p, event=event, channel="project")
        for p in (*site[1:4], alias)
    ] == [True, True, False, False]
    wrong = deepcopy(event)
    wrong["data"]["elaborato_revision_id"] = str(uuid.uuid4())
    assert not document_event_allowed(profile=site[1], event=wrong, channel="project")
    assert document_event_allowed(
        profile=site[3], event={"type": "post.created", "projectId": site[0].pk}, channel="project"
    )


def test_queued_push_rechecks_document_scope_before_provider(site, issued, monkeypatch):
    from edilcloud.modules.notifications.outbox import process_push_job

    revision, document, _ = issued
    item = notice(site[3], revision, document)
    job = NotificationPushJob.objects.create(notification=item, state="pending")
    sent = []
    monkeypatch.setattr("edilcloud.modules.notifications.push.push_enabled", lambda: True)
    monkeypatch.setattr(
        "edilcloud.modules.notifications.push.dispatch_notification_push",
        lambda n: sent.append(n.pk),
    )
    monkeypatch.setattr(
        "edilcloud.modules.notifications.outbox._project_push_allowed", lambda n: True
    )
    assert process_push_job(item.pk)
    job.refresh_from_db()
    assert job.state == "skipped" and job.last_error == "DOCUMENT_ACCESS" and sent == []


@pytest.mark.parametrize(
    "revoke_before,revoke_between,expected_calls,expected_state",
    [(False, False, 2, "complete"), (True, False, 0, "skipped"), (False, True, 1, "skipped")],
)
def test_push_company_revocation_preserves_deliveries_and_stops_remaining_devices(
    site, issued, monkeypatch, revoke_before, revoke_between, expected_calls, expected_state
):
    from edilcloud.modules.notifications.models import NotificationDevice, NotificationPushDelivery
    from edilcloud.modules.notifications.outbox import process_push_job

    revision, document, _ = issued
    worker = site[2]
    item = notice(worker, revision, document)
    assert notification_delivery_allowed(item)
    job = NotificationPushJob.objects.create(notification=item, state="pending")
    for token in ("private-qa-first", "private-qa-second"):
        NotificationDevice.objects.create(user=worker.user, profile=worker, token=token)
    calls = []

    def revoke():
        Profile.objects.filter(pk=worker.pk).update(workspace_id=site[3].workspace_id)

    def send(*, device, notification):
        calls.append(device.pk)
        if revoke_between:
            revoke()
        return f"projects/fixture/messages/{device.pk}"

    monkeypatch.setattr("edilcloud.modules.notifications.push.push_enabled", lambda: True)
    monkeypatch.setattr("edilcloud.modules.notifications.push._send_push", send)
    if revoke_before:
        revoke()
    assert process_push_job(item.pk)
    job.refresh_from_db()
    assert len(calls) == expected_calls
    assert job.state == expected_state
    assert job.last_error == ("DOCUMENT_ACCESS" if expected_state == "skipped" else "")
    assert NotificationPushDelivery.objects.filter(notification=item).count() == expected_calls
    assert NotificationPushDelivery.objects.filter(notification=item, status="sent").count() == expected_calls


def test_only_explicit_ordinary_deletion_survives_missing_target(site, issued):
    revision, document, _ = issued
    worker = site[2]
    item = notice(
        worker,
        revision,
        document,
        document_id=987654,
        object_id=987654,
        kind="project.document.deleted",
        data={"document_origin": "ordinary_upload"},
    )
    event = {
        "type": "document.deleted",
        "documentId": 987654,
        "projectId": site[0].pk,
        "data": item.data,
    }
    assert notification_delivery_allowed(item)
    assert document_event_allowed(profile=worker, event=event, channel="project")
    item.data = {}
    item.save(update_fields=("data",))
    assert not notification_delivery_allowed(item)
    assert not document_event_allowed(
        profile=worker, event={**event, "data": {}}, channel="project"
    )
    ProjectMember.objects.filter(profile=worker, project=site[0]).update(disabled=True)
    assert not document_event_allowed(profile=worker, event=event, channel="project")


def test_publication_audience_uses_company_or_exact_legacy_creator(site, issued):
    from edilcloud.modules.elaborati.visibility import publication_group, publication_recipients

    revision, _, alias = issued
    candidates = [*site[1:4], alias]
    assert publication_group(revision) == f"projects.{site[0].pk}.workspace.{site[1].workspace_id}"
    assert [p.pk for p in publication_recipients(revision=revision, candidates=candidates)] == [
        site[1].pk,
        site[2].pk,
    ]
    ElaboratoOwnership.objects.filter(document_id=revision.elaborato_id).delete()
    # Access the authoritative ownership again instead of a cached relation.
    revision.refresh_from_db()
    assert publication_group(revision) == f"projects.{site[0].pk}.profile.{site[1].pk}"
    assert [p.pk for p in publication_recipients(revision=revision, candidates=candidates)] == [
        site[1].pk
    ]


def test_socket_delivery_rechecks_document_and_revoked_auth_session(site, issued):
    from datetime import timedelta
    from unittest.mock import AsyncMock
    from asgiref.sync import async_to_sync
    from django.utils import timezone
    from edilcloud.modules.identity.models import AuthTokenSession
    from edilcloud.platform.realtime.consumers import ProjectRealtimeConsumer

    revision, document, _ = issued
    worker = site[2]
    session = AuthTokenSession.objects.create(
        user=worker.user,
        current_profile_id=worker.pk,
        expires_at=timezone.now() + timedelta(hours=1),
    )
    consumer = ProjectRealtimeConsumer()
    consumer.scope = {
        "realtime": {
            "channel": "project",
            "project_id": site[0].pk,
            "profile_id": worker.pk,
            "user_id": worker.user_id,
            "workspace_id": worker.workspace_id,
            "auth_session": str(session.session_token),
        }
    }
    consumer.send_json = AsyncMock()
    consumer.close = AsyncMock()
    payload = {
        "type": "document.created",
        "projectId": site[0].pk,
        "documentId": document.pk,
        "data": {"elaborato_revision_id": str(revision.pk)},
    }
    async_to_sync(consumer.realtime_event)({"payload": payload})
    consumer.send_json.assert_awaited_once_with(payload)
    consumer.send_json.reset_mock()
    ElaboratoOwnership.objects.filter(document_id=revision.elaborato_id).delete()
    async_to_sync(consumer.realtime_event)({"payload": payload})
    consumer.send_json.assert_not_awaited()
    consumer.close.assert_not_awaited()
    session.revoked_at = timezone.now()
    session.save(update_fields=("revoked_at",))
    async_to_sync(consumer.realtime_event)({"payload": {"type": "post.created"}})
    consumer.close.assert_awaited_once_with(code=4403)


def test_notification_socket_checks_stored_recipient_and_target(site, issued):
    revision, document, _ = issued
    item = notice(site[2], revision, document)
    event = {
        "type": "notification.created",
        "notificationId": item.pk,
        "profileId": site[2].pk,
        "documentId": document.pk,
        "data": item.data,
    }
    assert document_event_allowed(profile=site[2], event=event, channel="notifications")
    assert not document_event_allowed(profile=site[3], event=event, channel="notifications")
    assert not document_event_allowed(
        profile=site[2], event={**event, "documentId": 987654}, channel="notifications"
    )
