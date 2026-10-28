from datetime import timedelta

import pytest
from django.test import Client

from edilcloud.modules.projects.feed_read_state import feed_unread_counts, record_feed_receipts
from edilcloud.modules.projects.models import PostComment, ProjectPost, ProjectPostSeenState
from edilcloud.modules.notifications.models import Notification
from tests.test_projects_api import auth_headers, create_project_fixture, create_workspace_profile


@pytest.mark.django_db
def test_global_feed_count_is_independent_of_pages_and_read_batches_reach_zero():
    client = Client()
    _, _, profile = create_workspace_profile(email="read-global@example.com", password="devpass123")
    project, task, _, _ = create_project_fixture(profile)
    for index in range(34):
        ProjectPost.objects.create(project=project, task=task, author=profile, text=f"Update {index}")
    total = ProjectPost.objects.filter(project=project).count()
    headers = auth_headers(client, email="read-global@example.com", password="devpass123")
    cursor = None
    visited = []
    while True:
        params = {"limit": 5, "lightweight": "true", **({"cursor": cursor} if cursor else {})}
        page = client.get("/api/v1/projects/feed", params, **headers).json()
        assert page["unread_count"] == total - len(visited)
        assert len(page["items"]) <= 5
        ids = [post["id"] for post in page["items"]]
        assert not set(ids).intersection(visited)
        response = client.post("/api/v1/projects/feed/seen", {
            "receipts": [{"post_id": post["id"], "seen_through": post["last_activity_at"]} for post in page["items"]],
        }, content_type="application/json", **headers)
        assert response.status_code == 200, response.content
        visited.extend(ids)
        assert response.json()["unread_count"] == total - len(visited)
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(visited) == total
    assert feed_unread_counts(profile)["unread_count"] == 0


@pytest.mark.django_db
def test_delayed_receipt_does_not_read_new_comments_or_rewind_a_newer_receipt():
    _, _, profile = create_workspace_profile(email="read-race@example.com", password="devpass123")
    _, _, _, post = create_project_fixture(profile)
    record_feed_receipts(profile=profile, post_ids=list(ProjectPost.objects.exclude(pk=post.pk).values_list("pk", flat=True)))
    original = post.updated_at
    comment = PostComment.objects.create(post=post, author=profile, text="New information")
    newest = original + timedelta(seconds=5)
    PostComment.objects.filter(pk=comment.pk).update(updated_at=newest)
    receipt = lambda through: record_feed_receipts(profile=profile, receipts=[{"post_id": post.id, "seen_through": through}])
    stale = receipt(original)
    assert stale["items"][0]["is_unread"] is True
    assert stale["unread_count"] == 1
    assert receipt(newest)["unread_count"] == 0
    assert receipt(original)["unread_count"] == 0
    assert ProjectPostSeenState.objects.get(post=post, profile=profile).seen_at == newest


@pytest.mark.django_db
def test_read_receipts_are_scoped_to_accessible_projects_and_emit_after_commit(django_capture_on_commit_callbacks, monkeypatch):
    from edilcloud.modules.projects import feed_read_state

    _, _, profile = create_workspace_profile(email="read-scope@example.com", password="devpass123")
    _, _, other = create_workspace_profile(email="read-other@example.com", password="devpass123")
    _, _, _, visible = create_project_fixture(profile)
    _, _, _, hidden = create_project_fixture(other)
    initial_count = feed_unread_counts(profile)["unread_count"]
    published = []
    monkeypatch.setattr(feed_read_state, "publish_notification_event", lambda **event: published.append(event))
    with django_capture_on_commit_callbacks(execute=True):
        result = record_feed_receipts(profile=profile, post_ids=[visible.id, hidden.id])
        assert not published
    assert result["count"] == 1
    assert not ProjectPostSeenState.objects.filter(profile=profile, post=hidden).exists()
    assert published[0]["payload"]["type"] == "feed.seen"
    assert published[0]["payload"]["profileId"] == profile.id
    assert published[0]["payload"]["data"]["unread_count"] == initial_count - 1


@pytest.mark.django_db
def test_notifications_over_one_hundred_can_be_scrolled_and_read_in_batches():
    client = Client()
    user, _, profile = create_workspace_profile(email="read-notifications@example.com", password="devpass123")
    Notification.objects.bulk_create([Notification(recipient_profile=profile, subject=f"Notice {index}") for index in range(125)])
    headers = auth_headers(client, email="read-notifications@example.com", password="devpass123")
    visited = []
    cursor = None
    while True:
        page = client.get("/api/v1/notifications", {"limit": 20, **({"cursor": cursor} if cursor else {})}, **headers).json()
        assert page["unread_count"] == 125 - len(visited)
        ids = [item["id"] for item in page["results"]]
        assert not set(ids).intersection(visited)
        result = client.post("/api/v1/notifications/read", {"notification_ids": ids}, content_type="application/json", **headers)
        assert result.status_code == 200, result.content
        visited.extend(ids)
        assert result.json()["unread_count"] == 125 - len(visited)
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(visited) == 125


@pytest.mark.django_db
def test_invalid_cursor_is_rejected_without_changing_reads():
    client = Client()
    _, _, profile = create_workspace_profile(email="read-cursor@example.com", password="devpass123")
    create_project_fixture(profile)
    headers = auth_headers(client, email="read-cursor@example.com", password="devpass123")
    for endpoint in ("/api/v1/projects/feed", "/api/v1/notifications"):
        response = client.get(endpoint, {"cursor": "invalid"}, **headers)
        assert response.status_code == 400
    assert ProjectPostSeenState.objects.filter(profile=profile).count() == 0


@pytest.mark.django_db(transaction=True)
def test_real_websocket_fanout_reaches_both_profile_sessions_and_not_another_workspace():
    from asgiref.sync import async_to_sync, sync_to_async
    from asgiref.testing import ApplicationCommunicator
    from edilcloud.platform.realtime.consumers import NotificationRealtimeConsumer
    from edilcloud.platform.realtime.services import issue_realtime_ticket, publish_notification_event

    user, _, profile = create_workspace_profile(email="read-sockets@example.com", password="devpass123")

    other_user, _, other_profile = create_workspace_profile(
        email="read-other-sockets@example.com", password="devpass123"
    )

    async def connect(socket_user, profile_id):
        ticket, _ = issue_realtime_ticket(user_id=socket_user.id, profile_id=profile_id, channel="notifications")
        socket = ApplicationCommunicator(NotificationRealtimeConsumer.as_asgi(), {
            "type": "websocket", "path": "/ws/realtime/notifications/", "headers": [],
            "query_string": f"ticket={ticket}".encode(), "subprotocols": [],
        })
        await socket.send_input({"type": "websocket.connect"})
        assert (await socket.receive_output())["type"] == "websocket.accept"
        return socket

    async def scenario():
        import json

        first, second, other = (
            await connect(user, profile.id), await connect(user, profile.id),
            await connect(other_user, other_profile.id),
        )
        try:
            event = {"eventId": "read-transport", "type": "feed.updated", "profileId": profile.id}
            await sync_to_async(publish_notification_event)(profile_id=profile.id, payload=event)
            for socket in (first, second):
                assert json.loads((await socket.receive_output())["text"]) == event
            assert await other.receive_nothing(timeout=.05)
            await first.send_input({"type": "websocket.receive", "text": '{"type":"ping"}'})
            assert json.loads((await first.receive_output())["text"]) == {"type": "pong"}
        finally:
            for socket in (first, second, other):
                await socket.send_input({"type": "websocket.disconnect", "code": 1000})
                await socket.wait()

    async_to_sync(scenario)()
