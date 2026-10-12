import json
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from edilcloud.modules.projects import services
from edilcloud.modules.projects.models import Project, ProjectActivity, ProjectMember, ProjectMemberStatus, ProjectPost, ProjectTask, PostComment
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceRole


def fixture():
    user = get_user_model().objects.create_user(email="perf@example.com", username="perf", password="perf-test")
    workspace = Workspace.objects.create(name="Performance", email=user.email)
    owner = Profile.objects.create(user=user, workspace=workspace, email=user.email, role=WorkspaceRole.OWNER, language="it")
    project = Project.objects.create(workspace=workspace, created_by=owner, name="Performance", date_start=date.today())
    ProjectMember.objects.create(project=project, profile=owner, role=WorkspaceRole.OWNER, status=ProjectMemberStatus.ACTIVE)
    workers = [owner]
    for n in range(8):
        worker_user = get_user_model().objects.create_user(email=f"worker{n}@example.com", username=f"worker{n}")
        worker = Profile.objects.create(user=worker_user, workspace=workspace, email=worker_user.email, role=WorkspaceRole.WORKER)
        ProjectMember.objects.create(project=project, profile=worker, role=WorkspaceRole.WORKER, status=ProjectMemberStatus.ACTIVE)
        workers.append(worker)
    task = ProjectTask.objects.create(project=project, name="Phase", assigned_company=workspace, date_start=date.today(), date_end=date.today() + timedelta(days=10), progress=40)
    return owner, project, task, workers


@pytest.mark.django_db
def test_task_queries_stay_bounded_and_compact_payload_preserves_assignments():
    owner, project, task, workers = fixture()
    def add_activity(n):
        activity = ProjectActivity.objects.create(task=task, title=f"Activity {n}", datetime_start=timezone.now(), datetime_end=timezone.now()+timedelta(days=1))
        activity.workers.set(workers[:3])
    add_activity(0)
    services.list_project_tasks(profile=owner, project_id=project.id)  # initialize company colors
    with CaptureQueriesContext(connection) as small:
        services.list_project_tasks(profile=owner, project_id=project.id, compact=True)
    for n in range(1, 30):
        add_activity(n)
    with CaptureQueriesContext(connection) as large:
        compact = services.list_project_tasks(profile=owner, project_id=project.id, compact=True)
    legacy = services.list_project_tasks(profile=owner, project_id=project.id)
    assert len(large) <= len(small) + 2
    assert len(large) <= 14
    assert len(compact["assignment_members"]) == len(workers)
    assert len(compact["tasks"][0]["activities"]) == 30
    assert len(json.dumps(compact, default=str)) < len(json.dumps(legacy, default=str)) * .55
    for row, old in zip(compact["tasks"][0]["activities"], legacy[0]["activities"]):
        assert row["can_assign_in_activity"] == []
        assert row["workers"] == old["workers"]
        assert row["workers_in_activity"] == old["workers_in_activity"]
        assert old["can_assign_in_activity"] == compact["assignment_members"]


@pytest.mark.django_db
def test_project_summary_counts_are_not_restricted_to_viewer_or_multiplied_by_joins():
    owner, project, task, workers = fixture()
    ProjectTask.objects.create(project=project, name="Second", date_start=date.today(), date_end=date.today(), progress=80)
    for n in range(7):
        ProjectPost.objects.create(project=project, task=task, author=owner, text=f"Post {n}", alert=n < 4)
    result = services.get_project_summary(profile=owner, project_id=project.id)
    assert result["team_count"] == len(workers)
    assert result["alert_count"] == 4
    assert result["progress_percentage"] == 60
    assert services.list_projects(profile=owner)[0] == result


@pytest.mark.django_db
def test_project_feed_is_scoped_paginated_and_preserves_summary_media_and_comments():
    owner, project, task, _workers = fixture()
    post = ProjectPost.objects.create(project=project, task=task, author=owner, text="Operational update", source_language="it")
    PostComment.objects.create(post=post, author=owner, text="Confirmed")
    PostComment.objects.create(post=post, author=owner, text="Deleted", is_deleted=True)
    other = Project.objects.create(workspace=owner.workspace, created_by=owner, name="Other", date_start=date.today())
    ProjectMember.objects.create(project=other, profile=owner, role=WorkspaceRole.OWNER, status=ProjectMemberStatus.ACTIVE)
    ProjectPost.objects.create(project=other, author=owner, text="Other project")
    page = services.list_project_feed(profile=owner, project_id=project.id, lightweight=True, limit=1)
    assert [p["id"] for p in page["items"]] == [post.id]
    assert page["items"][0]["comment_count"] == 1
    assert page["items"][0]["comment_set"] == []
    assert page["items"][0]["text"] == "Operational update"
    assert page["has_more"] is False
    assert len(services.list_project_feed(profile=owner, project_id=project.id)["items"][0]["comment_set"]) >= 1
    ProjectMember.objects.filter(project=other).delete()
    with pytest.raises(ValueError):
        services.list_project_feed(profile=owner, project_id=other.id, lightweight=True)


@pytest.mark.django_db
def test_summary_previews_count_comments_without_materializing_threads(monkeypatch):
    owner, project, task, _workers = fixture()
    post = ProjectPost.objects.create(project=project, task=task, author=owner, text="Update", alert=True)
    PostComment.objects.bulk_create([
        PostComment(post=post, author=owner, text=f"Reply {n}") for n in range(120)
    ])
    latest = timezone.now() + timedelta(seconds=10)
    deleted = PostComment.objects.create(post=post, author=owner, text="Deleted", is_deleted=True)
    PostComment.objects.filter(pk=deleted.pk).update(updated_at=latest)

    def unexpected(cls, *args, **kwargs):
        pytest.fail("Summary read models must not construct comment records")

    with monkeypatch.context() as patch:
        patch.setattr(PostComment, "from_db", classmethod(unexpected))
        results = [
            services.list_project_feed(profile=owner, project_id=project.id, lightweight=True)["items"],
            services.list_project_recent_posts(profile=owner, project_id=project.id, lightweight=True),
            services.list_project_alert_posts(profile=owner, project_id=project.id, lightweight=True),
        ]
        for rows in results:
            assert len(rows) == 1
            assert rows[0]["comment_count"] == 120
            assert rows[0]["comment_set"] == []
            assert rows[0]["last_activity_at"] == latest
    full = services.list_project_feed(profile=owner, project_id=project.id)
    assert len(full["items"][0]["comment_set"]) >= 120


@pytest.mark.django_db
def test_existing_demo_assets_are_not_rebuilt_during_navigation(monkeypatch):
    from edilcloud.modules.assistant.models import ProjectAssistantGraphSnapshot, ProjectAssistantWikiPage
    from edilcloud.modules.projects.demo_master_admin import ensure_demo_master_assistant_assets
    owner, project, _task, _workers = fixture()
    from edilcloud.modules.assistant.services import get_or_create_project_assistant_state
    get_or_create_project_assistant_state(project)
    ProjectAssistantGraphSnapshot.objects.create(project=project)
    ProjectAssistantWikiPage.objects.create(project=project, slug="summary", title="Summary", page_type="summary")
    def unexpected(*args, **kwargs):
        pytest.fail("Navigation must not rebuild existing assistant assets")
    monkeypatch.setattr("edilcloud.modules.assistant.graph_service.rebuild_project_graph", unexpected)
    monkeypatch.setattr("edilcloud.modules.assistant.wiki_service.rebuild_project_wiki", unexpected)
    monkeypatch.setattr("edilcloud.modules.assistant.indexing_service.ensure_project_index_scheduled", unexpected)
    ensure_demo_master_assistant_assets(project)


@pytest.mark.django_db
def test_file_sizes_are_written_once_and_reads_never_touch_storage(tmp_path, settings, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from edilcloud.modules.projects.models import ProjectDocument, ProjectPhoto, PostAttachment
    settings.MEDIA_ROOT = tmp_path
    owner, project, task, _workers = fixture()
    document = ProjectDocument.objects.create(project=project, title="Plan", document=SimpleUploadedFile("plan.pdf", b"plan"))
    photo = ProjectPhoto.objects.create(project=project, photo=SimpleUploadedFile("photo.jpg", b"image"))
    post = ProjectPost.objects.create(project=project, task=task, author=owner, text="Update")
    attachment = PostAttachment.objects.create(post=post, file=SimpleUploadedFile("voice.mp3", b"audio"))
    assert (document.file_size, photo.file_size, attachment.file_size) == (4, 5, 5)
    document.document = SimpleUploadedFile("new.pdf", b"replacement")
    document.save(update_fields=["document"])
    document.refresh_from_db()
    assert document.file_size == 11
    def unexpected(*args, **kwargs):
        pytest.fail("Read models must not query storage for file sizes")
    monkeypatch.setattr(document.document.storage, "size", unexpected)
    assert services.serialize_document(document)["size"] == 11
    assert services.serialize_photo(photo)["size"] == 5
    assert services.attachment_size(attachment.file) == 5
    ProjectDocument.objects.filter(pk=document.pk).update(file_size=None)
    document.refresh_from_db()
    assert services.serialize_document(document)["size"] is None


@pytest.mark.django_db
def test_file_size_backfill_is_idempotent_and_does_not_rewrite_files(tmp_path, settings):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.management import call_command
    from edilcloud.modules.projects.models import ProjectDocument
    settings.MEDIA_ROOT = tmp_path
    _owner, project, _task, _workers = fixture()
    document = ProjectDocument.objects.create(project=project, title="Plan", document=SimpleUploadedFile("plan.pdf", b"legacy"))
    original_name, original_updated = document.document.name, document.updated_at
    ProjectDocument.objects.filter(pk=document.pk).update(file_size=None)
    call_command("backfill_file_sizes")
    call_command("backfill_file_sizes")
    document.refresh_from_db()
    assert document.file_size == 6
    assert document.document.name == original_name
    assert document.updated_at == original_updated


@pytest.mark.django_db
def test_storage_quota_uses_persisted_sizes_but_still_counts_legacy_files(tmp_path, settings, monkeypatch):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from edilcloud.modules.billing import services as billing
    from edilcloud.modules.projects.models import ProjectDocument
    settings.MEDIA_ROOT = tmp_path
    owner, project, _task, _workers = fixture()
    document = ProjectDocument.objects.create(project=project, title="Plan", document=SimpleUploadedFile("plan.pdf", b"legacy"))
    def unexpected(*args, **kwargs):
        pytest.fail("Quota calculation must not stat files with known sizes")
    with monkeypatch.context() as patch:
        patch.setattr(billing, "storage_size_for_name", unexpected)
        assert billing.calculate_workspace_storage_usage(owner.workspace) == 6
    ProjectDocument.objects.filter(pk=document.pk).update(file_size=None)
    assert billing.calculate_workspace_storage_usage(owner.workspace) == 6
