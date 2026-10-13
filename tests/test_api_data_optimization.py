"""Contracts, permissions, query/byte budgets and asynchronous read regressions."""
import json
from datetime import date
from unittest.mock import Mock

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import connection
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from edilcloud.modules.files.responses import inline_file_response
from edilcloud.modules.projects import services as s
from edilcloud.modules.projects.read_context import pure_read_models
from edilcloud.modules.projects.models import ProjectActivity, ProjectDocument, ProjectDrawingPin, ProjectPost, PostComment
from tests.test_project_performance_regressions import fixture


@pytest.mark.django_db
def test_normalized_directory_recovers_every_legacy_assignment_and_reduces_bytes():
    owner, project, task, workers = fixture()
    for n in range(30):
        activity = ProjectActivity.objects.create(task=task, title=f"Activity {n}", datetime_start=timezone.now(), datetime_end=timezone.now())
        activity.workers.set(workers[:3])
    old = s.list_project_tasks(profile=owner, project_id=project.id)
    compact = s.list_project_tasks(profile=owner, project_id=project.id, compact=True)
    with CaptureQueriesContext(connection) as queries:
        normalized = s.list_project_tasks(profile=owner, project_id=project.id, normalized=True)
    assert len(queries) <= 14
    assert normalized["contract_version"] == 2
    members = {row["id"]: row for row in normalized["assignment_members"]}
    profiles = {row["id"]: row for row in normalized["worker_profiles"]}
    for phase in normalized["tasks"]:
        for activity in phase["activities"]:
            assert "workers" not in activity and "workers_in_activity" not in activity
            activity["workers"] = [profiles[key] for key in activity.pop("worker_profile_ids")]
            activity["workers_in_activity"] = [members[key] for key in activity.pop("worker_member_ids")]
            activity["can_assign_in_activity"] = normalized["assignment_members"]
    assert normalized["tasks"] == old
    result = s.list_project_tasks(profile=owner, project_id=project.id, normalized=True)
    assert len(json.dumps(result, default=str)) < len(json.dumps(compact, default=str)) * .5
    gantt = s.list_project_gantt(profile=owner, project_id=project.id, normalized=True)
    assert gantt["tasks"] == result["tasks"]
    assert gantt["worker_profiles"] == result["worker_profiles"]


@pytest.mark.django_db
def test_selected_post_is_filtered_before_page_and_preserves_discussion_and_scope():
    owner, project, task, _ = fixture()
    old = ProjectPost.objects.create(project=project, task=task, author=owner, text="Old", source_language="it")
    PostComment.objects.create(post=old, author=owner, text="Reply", source_language="it")
    for n in range(25):
        ProjectPost.objects.create(project=project, task=task, author=owner, text=f"New {n}", source_language="it")
    assert old.id not in [p["id"] for p in s.list_posts_for_task(profile=owner, task_id=task.id, limit=10)]
    selected = s.list_posts_for_task(profile=owner, task_id=task.id, limit=1, post_id=old.id)
    assert [p["id"] for p in selected] == [old.id]
    assert selected[0]["comment_set"][0]["text"] == "Reply"
    assert s.list_project_feed(profile=owner, post_id=old.id, limit=1)["items"][0]["id"] == old.id
    first = s.list_posts_for_task(profile=owner, task_id=task.id, limit=10)
    second = s.list_posts_for_task(profile=owner, task_id=task.id, limit=10, offset=10)
    assert not {p["id"] for p in first} & {p["id"] for p in second}
    summary = s.list_posts_for_task(profile=owner, task_id=task.id, post_id=old.id, lightweight=True)[0]
    assert summary["comment_count"] == 1 and summary["comment_set"] == []


@pytest.mark.django_db
@override_settings(PROJECT_CONTENT_TRANSLATION_ASYNC=True)
def test_get_translation_miss_queues_without_provider_call_or_database_write(monkeypatch):
    owner, project, task, _ = fixture()
    post = ProjectPost.objects.create(project=project, task=task, author=owner, text="Hello", source_language="en")
    queue = Mock()
    monkeypatch.setattr("edilcloud.modules.projects.translation_jobs.enqueue_translation", queue)
    provider = Mock(side_effect=AssertionError("Provider called in HTTP read"))
    monkeypatch.setattr(s, "generate_project_content_translation", provider)
    with pure_read_models(), CaptureQueriesContext(connection) as queries:
        result = s.list_posts_for_task(profile=owner, task_id=task.id, target_language="it")
    assert result[0]["text"] == "Hello"
    assert result[0]["translation_status"] == "pending"
    queue.assert_called_once()
    provider.assert_not_called()
    assert not any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)


@pytest.mark.django_db
def test_overview_summary_counts_and_bounded_sections_do_not_drop_full_data():
    owner, project, task, _ = fixture()
    for n in range(13):
        ProjectDocument.objects.create(project=project, title=f"Document {n}", document_kind="document")
        ProjectPost.objects.create(project=project, task=task, author=owner, text=f"Issue {n}", alert=True, source_language="it")
    full = s.get_project_overview(profile=owner, project_id=project.id)
    with CaptureQueriesContext(connection) as queries:
        summary = s.get_project_overview(profile=owner, project_id=project.id, view="summary")
    assert summary["document_count"] == summary["alert_count"] == 13
    assert len(summary["documents"]) == len(summary["alertPosts"]) == 8
    assert len(full["documents"]) == len(full["alertPosts"]) == 13
    assert len(summary["recentPosts"]) == 8
    assert len(queries) <= 25


@pytest.mark.django_db
def test_drawing_summary_keeps_counts_filters_and_does_not_load_comments():
    owner, project, task, _ = fixture()
    document = ProjectDocument.objects.create(project=project, title="Drawing", document_kind="drawing")
    post = ProjectPost.objects.create(project=project, task=task, author=owner, text="Issue", source_language="it")
    PostComment.objects.bulk_create([PostComment(post=post, author=owner, text=f"Reply {n}", source_language="it") for n in range(80)])
    for page in (1, 2):
        ProjectDrawingPin.objects.create(project=project, drawing_document=document, post=post, page_number=page, x=.2, y=.4)
    with CaptureQueriesContext(connection) as queries:
        summary = s.list_project_drawing_pins(profile=owner, project_id=project.id, view="summary", page=2)
    assert len(summary) == 1 and summary[0]["page_number"] == 2
    assert summary[0]["post"]["comment_count"] == 80
    assert summary[0]["post"]["comment_set"] == []
    # A COUNT subquery is allowed; fetching the comment rows is not.
    assert not any(q["sql"].lstrip().startswith('SELECT "projects_postcomment".') for q in queries)
    full = s.list_project_drawing_pins(profile=owner, project_id=project.id, page=2)
    assert len(full[0]["post"]["comment_set"]) == 80
    assert len(json.dumps(summary, default=str)) < len(json.dumps(full, default=str)) * .2


@pytest.mark.django_db(transaction=True)
def test_translation_worker_deduplicates_and_publishes_completion(monkeypatch):
    from edilcloud.modules.projects import translation_jobs as jobs
    cache.clear()
    owner, project, task, _ = fixture()
    post = ProjectPost.objects.create(project=project, task=task, author=owner, text="Worker hello", source_language="en")
    provider = Mock(return_value="Ciao dal worker")
    monkeypatch.setattr(s, "generate_project_content_translation", provider)
    monkeypatch.setattr(s, "emit_feed_refresh_for_post", Mock())
    monkeypatch.setattr(s, "publish_project_event", Mock())
    submit = Mock()
    monkeypatch.setattr(jobs._executor, "submit", submit)
    signature = s.build_project_content_translation_signature(source_text=post.text, source_language="en")
    args = dict(kind="post", entity_id=post.id, target_language="it", source_signature=signature)
    jobs.enqueue_translation(**args)
    jobs.enqueue_translation(**args)
    submit.assert_called_once()
    function, *arguments = submit.call_args.args
    function(*arguments)
    provider.assert_called_once()
    s.emit_feed_refresh_for_post.assert_called_once()
    with override_settings(PROJECT_CONTENT_TRANSLATION_ASYNC=True):
        result = s.resolve_post_translation_memory([post], target_language="it", fallback_language="it")
    assert result[post.id].translated_text == "Ciao dal worker"
    assert s.localized_post_content(post, translation=result[post.id])["translation_status"] == "ready"


@pytest.mark.django_db
def test_normalized_feed_profiles_preserve_authors_and_nested_replies():
    owner, project, task, _ = fixture()
    post = ProjectPost.objects.create(project=project, task=task, author=owner, text="Update", source_language="it")
    parent = PostComment.objects.create(post=post, author=owner, text="Parent", source_language="it")
    PostComment.objects.create(post=post, parent=parent, author=owner, text="Reply", source_language="it")
    legacy = s.list_project_feed(profile=owner, post_id=post.id)
    compact = s.list_project_feed(profile=owner, post_id=post.id, normalized=True)
    assert len(compact["included"]["profiles"]) == 1
    profile = compact["included"]["profiles"][0]
    assert compact["items"][0]["author"] == {"id": owner.id}
    assert compact["items"][0]["comment_set"][0]["replies_set"][0]["author"] == {"id": owner.id}
    def expand(row):
        return {**row, "author": profile, **{key: [expand(item) for item in row[key]]
            for key in ("comment_set", "replies_set") if key in row}}
    assert [expand(row) for row in compact["items"]] == legacy["items"]


@pytest.mark.django_db
def test_assistant_pure_read_does_not_provision_or_write_and_windows_keep_history():
    from edilcloud.modules.assistant import services as assistant
    from edilcloud.modules.assistant.models import ProjectAssistantMessage, AssistantMessageRole
    owner, project, _, _ = fixture()
    with pure_read_models(), CaptureQueriesContext(connection) as queries:
        empty = assistant.get_project_assistant_state(profile=owner, project_id=project.id, message_limit=10)
    assert empty["messages"] == [] and empty["active_thread_id"] is None
    assert not any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)
    thread = assistant.create_project_assistant_thread(project=project, profile=owner, title="History")
    for n in range(23):
        ProjectAssistantMessage.objects.create(project=project, thread=thread, author=owner, role=AssistantMessageRole.USER, content=f"Message {n}")
    with pure_read_models():
        first = assistant.get_project_assistant_state(profile=owner, project_id=project.id, thread_id=thread.id, message_limit=10)
        second = assistant.get_project_assistant_state(profile=owner, project_id=project.id, thread_id=thread.id, message_limit=10, cursor=first["next_message_cursor"])
        last = assistant.get_project_assistant_state(profile=owner, project_id=project.id, thread_id=thread.id, message_limit=10, cursor=second["next_message_cursor"])
    ids = [row["id"] for page in (first, second, last) for row in page["messages"]]
    assert len(ids) == len(set(ids)) == 23
    assert last["has_more_messages"] is False
    with pytest.raises(ValueError), pure_read_models():
        assistant.get_project_assistant_state(profile=owner, project_id=project.id, message_limit=10, cursor=first["next_message_cursor"] + "x")


@pytest.mark.django_db
def test_assistant_pure_budget_counts_owned_workspaces_without_provisioning_links():
    from edilcloud.modules.assistant import services as assistant
    from edilcloud.modules.assistant.models import ProjectAssistantMessage, ProjectAssistantUsage, AssistantMessageRole
    from edilcloud.modules.billing.models import BillingWorkspace
    from edilcloud.modules.billing.services import get_workspace_billing_account
    from edilcloud.modules.projects.models import Project
    from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole

    owner, project, _, _ = fixture()
    account = get_workspace_billing_account(project.workspace)
    sibling = Workspace.objects.create(name="Unlinked workspace", email=owner.email)
    sibling_owner = Profile.objects.create(
        user=owner.user, workspace=sibling, email=owner.email, role=WorkspaceRole.OWNER,
    )
    sibling_project = Project.objects.create(
        workspace=sibling, created_by=sibling_owner, name="Sibling", date_start=date.today(),
    )
    message = ProjectAssistantMessage.objects.create(
        project=sibling_project, author=sibling_owner,
        role=AssistantMessageRole.ASSISTANT, content="An answer",
    )
    ProjectAssistantUsage.objects.create(
        project=sibling_project, profile=sibling_owner, assistant_message=message, total_tokens=777,
    )
    with pure_read_models(), CaptureQueriesContext(connection) as queries:
        budget = assistant.serialize_assistant_token_budget(project=project, profile=owner, monthly_limit=1)
    assert budget["monthly_limit"] == account.monthly_ai_tokens_base
    assert budget["monthly_used"] == 777
    assert budget["project_monthly_used"] == 0
    assert not BillingWorkspace.objects.filter(workspace=sibling).exists()
    assert not any(q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries)


@pytest.mark.django_db
def test_timeline_keyset_scope_and_history_are_preserved():
    from edilcloud.modules.projects.models import ProjectOperationalEvent
    from edilcloud.modules.projects.operational_history import list_project_operational_timeline
    owner, project, task, _ = fixture()
    for n in range(13):
        ProjectOperationalEvent.objects.create(project=project, event_type="post.created", occurred_at=timezone.now(), task_id_snapshot=task.id, payload={"timeline": {"id": str(n), "label": f"Event {n}"}})
    first = list_project_operational_timeline(project_id=project.id, mode="general", task_id=task.id, limit=10)
    second = list_project_operational_timeline(project_id=project.id, mode="general", task_id=task.id, limit=10, cursor=first["next_cursor"])
    assert len(first["events"]) == 10 and len(second["events"]) == 3
    assert len({row["id"] for row in first["events"] + second["events"]}) == 13
    with pytest.raises(ValueError):
        list_project_operational_timeline(project_id=project.id + 1, mode="general", task_id=task.id, limit=10, cursor=first["next_cursor"])


@pytest.mark.django_db
@pytest.mark.parametrize("range_header,expected,status", [
    ("bytes=2-5", b"2345", 206), ("bytes=7-", b"789", 206),
    ("bytes=-3", b"789", 206), ("bytes=99-", b"", 416),
    ("bytes=-0", b"", 416), ("", b"0123456789", 200),
])
def test_file_streaming_ranges(tmp_path, range_header, expected, status):
    from django.core.files import File
    path = tmp_path / "video.mp4"
    path.write_bytes(b"0123456789")
    with path.open("rb") as handle:
        file = File(handle, name=str(path))
        request = RequestFactory().get("/file", HTTP_RANGE=range_header)
        response = inline_file_response(file, filename="video.mp4", content_type="video/mp4", request=request)
        assert response.status_code == status
        body = b"".join(response.streaming_content) if response.streaming else response.content
        assert body == expected
        if status == 206:
            assert response["Content-Length"] == str(len(expected))
            assert response["Content-Range"].endswith("/10")
        response.close()


@pytest.mark.django_db
def test_file_conditional_requests_and_if_range(tmp_path):
    from django.core.files import File
    path = tmp_path / "photo.webp"
    path.write_bytes(b"0123456789")
    def request(**headers):
        return inline_file_response(File(path.open("rb"), name=str(path)), filename="photo.webp",
            content_type="image/webp", request=RequestFactory().get("/file", **headers))
    initial = request()
    etag = initial["ETag"]
    modified = initial["Last-Modified"]
    initial.close()
    response = request(HTTP_IF_NONE_MATCH=etag)
    assert response.status_code == 304 and response.content == b""
    assert request(HTTP_IF_MODIFIED_SINCE=modified).status_code == 304
    response = request(HTTP_RANGE="bytes=0-1", HTTP_IF_RANGE='"old"')
    assert response.status_code == 200
    response.close()
    response = request(HTTP_RANGE="bytes=0-1", HTTP_IF_RANGE=etag)
    assert response.status_code == 206
    assert b"".join(response.streaming_content) == b"01"
    response.close()
