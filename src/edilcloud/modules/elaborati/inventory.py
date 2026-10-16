"""Exhaustive permission-scoped census. Batch sizes never discard records.

Materialized records are immutable for a run. Reading files and calling a model
are separate stages; neither happens while an inventory database page is read.
"""

from datetime import datetime, time, timedelta
from pathlib import PurePosixPath

from django.db.models import Q
from django.utils import timezone

from edilcloud.modules.projects.models import (
    CommentAttachment, PostComment, ProjectActivity, ProjectDocument, ProjectDrawingPin,
    ProjectMemberStatus, ProjectOperationalEvent, ProjectPhoto, PostAttachment,
)
from edilcloud.modules.projects.services import get_project_for_profile, profile_display_name

from .content import digest
from .evidence import file_version
from .models import DocumentEvidenceItem, DocumentJob, ElaboratoRevision
from .policies import policy_for

BATCH_SIZE = 100


def pages(queryset, size=BATCH_SIZE):
    """Keyset pages rather than a growing OFFSET or an unbounded result list."""
    cursor = None
    while True:
        query = queryset.filter(pk__gt=cursor) if cursor is not None else queryset
        batch = list(query.order_by("pk")[:size])
        if not batch:
            return
        yield from batch
        cursor = batch[-1].pk


def source(kind, pk, data, *, at=None, file_ref=None, parent_id=None):
    value = {
        "id": f"{kind}:{pk}", "kind": kind, "record_id": str(pk), "data": data,
        "at": at.isoformat() if at else None, "parent_id": parent_id,
    }
    if file_ref:
        value["file_ref"] = file_ref
        value["file_version"] = file_ref.get("version", "")
    value["hash"] = digest({k: v for k, v in value.items() if k != "file_ref"})
    return value


def media_data(field, context, event_at):
    name = PurePosixPath(field.name).name
    extension = PurePosixPath(name).suffix.lower()
    media = (
        "image" if extension in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}
        else "audio" if extension in {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".webm"}
        else "video" if extension in {".mp4", ".mov", ".mkv"}
        else "file"
    )
    return {
        "filename": name, "context": context, "media_kind": media,
        "visual_content_verified": False,
        "event_date_from_parent": event_at.isoformat() if event_at else None,
        "uploaded_at_is_not_event_date": True,
    }


def project_sources(*, job, captured_at, batch_size=BATCH_SIZE):
    document = job.revision.elaborato
    scope = policy_for(document.document_type).scope_rules
    project = get_project_for_profile(profile=job.requested_by, project_id=document.project_id)
    start = timezone.make_aware(datetime.combine(document.period_start, time.min))
    end = timezone.make_aware(datetime.combine(document.period_end + timedelta(days=1), time.min))
    yield source("project", project.pk, {
        "name": project.name, "address": project.address, "description": project.description,
        "company": project.workspace.name, "date_start": str(project.date_start),
        "date_end": str(project.date_end or ""),
        "context_declared_by_author": document.context,
    })
    yield source("request", document.pk, {
        "document_type": document.document_type, "period_start": str(document.period_start),
        "period_end": str(document.period_end), "language": document.language,
        "context": document.context, "declared_parameters": True,
        "requested_by": profile_display_name(job.requested_by),
    }, at=document.created_at)
    for declaration in job.revision.declarations:
        yield source("declaration", declaration["id"], {
            "text": declaration["text"], "declared_by": declaration["author"],
            "declared_at": declaration["at"], "nature": "reported",
            **({"document_field": declaration["field"]} if declaration.get("field") else {}),
        })
    members = project.members.filter(
        status=ProjectMemberStatus.ACTIVE, disabled=False, created_at__lte=captured_at,
    ).select_related("profile__workspace", "profile__user")
    for member in pages(members, batch_size):
        yield source("member", member.pk, {
            "name": profile_display_name(member.profile), "profile_id": member.profile_id,
            "role": member.role, "professional_roles": member.project_role_codes,
            "company": member.profile.workspace.name, "presence": "unknown",
        })
    period_comments = PostComment.objects.filter(
        post__project=project, post__is_deleted=False, is_deleted=False,
        created_at__gte=start, created_at__lt=end, created_at__lte=captured_at,
    )
    posts = project.posts.filter(
        is_deleted=False, published_date__lt=end, created_at__lte=captured_at,
    )
    if scope.posts != "project_history_until_reference_end":
        posts = posts.filter(Q(published_date__gte=start) | Q(pk__in=period_comments.values("post_id")))
    post_rows = posts.select_related("author", "task", "activity")
    for post in pages(post_rows, batch_size):
        text = post.original_text or post.text
        yield source("post", post.pk, {
            "text": text, "author": profile_display_name(post.author), "post_kind": post.post_kind,
            "task": post.task.name if post.task else None,
            "activity": post.activity.title if post.activity else None,
            "alert": post.alert, "weather_recorded": post.weather_snapshot or {},
            "outside_period_context": not start <= post.published_date < end,
        }, at=post.published_date)
    post_attachments = PostAttachment.objects.filter(
        post__in=posts.values("pk"), created_at__lte=captured_at,
    ).select_related("post")
    for attachment in pages(post_attachments, batch_size):
        post = attachment.post
        data = media_data(attachment.file, post.original_text or post.text, post.published_date)
        kind = "image_attachment" if data["media_kind"] == "image" else "attachment"
        yield source(kind, attachment.pk, data, at=attachment.created_at,
                     parent_id=f"post:{post.pk}", file_ref={
                         "model": "post_attachment", "id": attachment.pk,
                         "version": file_version(attachment, "file"),
                     })
    # Include the entire selected conversation up to the requested reference
    # end. Older comments are context, never silently represented as today's.
    comments = PostComment.objects.filter(
        post__in=posts.values("pk"), is_deleted=False, created_at__lt=end,
        created_at__lte=captured_at,
    ).select_related("author")
    if scope.comments == "period_only":
        comments = comments.filter(created_at__gte=start)
    for comment in pages(comments, batch_size):
        yield source("comment", comment.pk, {
            "text": comment.original_text or comment.text,
            "author": profile_display_name(comment.author),
            "outside_period_context": not start <= comment.created_at < end,
        }, at=comment.created_at, parent_id=f"post:{comment.post_id}")
    attachments = CommentAttachment.objects.filter(
        comment__in=comments.values("pk"), created_at__lte=captured_at,
    ).select_related("comment")
    for attachment in pages(attachments, batch_size):
        data = media_data(attachment.file,
                          attachment.comment.original_text or attachment.comment.text,
                          attachment.comment.created_at)
        kind = "image_attachment" if data["media_kind"] == "image" else "attachment"
        yield source(kind, f"comment-{attachment.pk}", data, at=attachment.created_at,
                     parent_id=f"comment:{attachment.comment_id}", file_ref={
                         "model": "comment_attachment", "id": attachment.pk,
                         "version": file_version(attachment, "file"),
                     })
    tasks = project.tasks.filter(
        date_start__lte=document.period_end, date_end__gte=document.period_start,
        created_at__lte=captured_at,
    ).select_related("assigned_company")
    for task in pages(tasks, batch_size):
        yield source("task", task.pk, {
            "name": task.name, "note": task.note,
            "company": task.assigned_company.name if task.assigned_company else None,
            "scheduled_start": str(task.date_start), "scheduled_end": str(task.date_end),
            "progress_current_snapshot": task.progress,
            "snapshot_is_not_period_end_progress": True,
        }, at=task.updated_at)
    activities = ProjectActivity.objects.filter(
        task__project=project, datetime_start__lt=end, datetime_end__gte=start,
        created_at__lte=captured_at,
    ).select_related("task")
    for activity in pages(activities, batch_size):
        yield source("activity", activity.pk, {
            "task": activity.task.name, "title": activity.title,
            "description": activity.description, "note": activity.note,
            "status_current_snapshot": activity.status,
        }, at=activity.updated_at)
    photos = ProjectPhoto.objects.filter(project=project, created_at__lt=end, created_at__lte=captured_at)
    if scope.photographs == "period_uploads":
        photos = photos.filter(created_at__gte=start)
    for photo in pages(photos, batch_size):
        yield source("photo", photo.pk, {
            "title": photo.title, "filename": PurePosixPath(photo.photo.name).name,
            "media_kind": "image", "visual_content_verified": False, "at_is_upload_date": True,
            "outside_period_context": not start <= photo.created_at < end,
        }, at=photo.created_at, file_ref={
            "model": "project_photo", "id": photo.pk, "version": file_version(photo, "photo"),
        })
    derived_ids = ElaboratoRevision.objects.filter(
        elaborato__project=project, drive_document_id__isnull=False,
    ).values("drive_document_id")
    documents = ProjectDocument.objects.filter(
        project=project, created_at__lte=captured_at,
    ).exclude(pk__in=derived_ids)
    for file in pages(documents, batch_size):
        yield source("drawing" if file.document_kind == "drawing" else "document", file.pk, {
            "title": file.title, "description": file.description,
            "filename": PurePosixPath(file.document.name).name,
            "file_content_extracted": False, "excerpts": [],
        }, at=file.updated_at, file_ref={
            "model": "document", "id": file.pk, "version": file_version(file, "document"),
        })
    pins = ProjectDrawingPin.objects.filter(
        project=project, post_id__in=posts.values("pk"), created_at__lte=captured_at,
    ).select_related("drawing_document")
    for pin in pages(pins, batch_size):
        yield source("drawing_pin", pin.pk, {
            "drawing": pin.drawing_document.title, "drawing_id": pin.drawing_document_id,
            "code": pin.pin_code, "label": pin.label, "page": pin.page_number,
            "x": pin.x, "y": pin.y,
        }, at=pin.created_at, parent_id=f"post:{pin.post_id}")
    events = ProjectOperationalEvent.objects.filter(
        project=project, occurred_at__lt=end, created_at__lte=captured_at,
    )
    if scope.operational_events == "period_only":
        events = events.filter(occurred_at__gte=start)
    for event in pages(events, batch_size):
        yield source("event", event.pk, {
            "type": event.event_type, "post_id": event.post_id_snapshot,
            "task_id": event.task_id_snapshot, "document_id": event.document_id_snapshot,
            "outside_period_context": not start <= event.occurred_at < end,
        }, at=event.occurred_at)


def build_inventory(job, *, batch_size=BATCH_SIZE):
    """Idempotent census; a process restart preserves materialized versions."""
    from .jobs import renew_lease

    job.refresh_from_db(fields=("workflow_state",))
    state = dict(job.workflow_state)
    if state.get("inventory_complete"):
        return inventory_counts(job)
    captured = state.get("inventory_started_at") or timezone.now().isoformat()
    state["inventory_started_at"] = captured
    DocumentJob.objects.filter(pk=job.pk, lease_token=job.lease_token).update(workflow_state=state)
    policy = policy_for(job.revision.elaborato.document_type)
    state["document_policy"] = policy.snapshot(job.revision.template_snapshot["sections"])
    for index, item in enumerate(project_sources(
        job=job, captured_at=datetime.fromisoformat(captured), batch_size=batch_size,
    )):
        permitted = item["kind"] in policy.allowed_sources
        DocumentEvidenceItem.objects.get_or_create(job=job, source_id=item["id"], defaults={
            "kind": item["kind"], "source_hash": item["hash"],
            "source_version": item.get("file_version", ""), "payload": item,
            "state": "pending" if permitted else "excluded",
            "reason": "" if permitted else "source_kind_outside_document_policy",
        })
        if index % batch_size == 0:
            renew_lease(job)
    state.update(inventory_complete=True, inventory_completed_at=timezone.now().isoformat())
    DocumentJob.objects.filter(pk=job.pk, lease_token=job.lease_token).update(workflow_state=state)
    return inventory_counts(job)


def inventory_counts(job):
    from django.db.models import Count

    roots = DocumentEvidenceItem.objects.filter(job=job, parent_source_id="")
    return {
        "total": roots.count(),
        "by_state": {r["state"]: r["n"] for r in roots.values("state").annotate(n=Count("pk"))},
        "by_kind": {r["kind"]: r["n"] for r in roots.values("kind").annotate(n=Count("pk"))},
    }
