"""Deterministic, bounded evidence. No model-driven SQL or remote retrieval.

The project APIs currently expose all project posts/documents to active members;
is_public is sharing metadata, not a second internal ACL. This builder uses that
same membership boundary and never traverses a different project/workspace.
"""

from datetime import datetime, time, timedelta
from pathlib import PurePosixPath

from django.utils import timezone

from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostComment,
    ProjectActivity,
    ProjectDocument,
    ProjectDrawingPin,
    ProjectMemberStatus,
    ProjectOperationalEvent,
    ProjectPhoto,
)
from edilcloud.modules.projects.services import get_project_for_profile, profile_display_name

from .content import digest, editor_claims


def file_version(obj, field):
    return digest({"name": getattr(obj, field).name, "updated_at": obj.updated_at.isoformat()})


def build_evidence(*, profile, elaborato, declarations=()) -> dict:
    project = get_project_for_profile(profile=profile, project_id=elaborato.project_id)
    start = timezone.make_aware(datetime.combine(elaborato.period_start, time.min))
    end = timezone.make_aware(datetime.combine(elaborato.period_end + timedelta(days=1), time.min))
    result = {
        "schema_version": 1,
        "captured_at": timezone.now().isoformat(),
        "project_id": project.pk,
        "period_start": elaborato.period_start.isoformat(),
        "period_end": elaborato.period_end.isoformat(),
        "sources": [],
        "truncated": False,
        "limits": {"sources": 450, "text_characters": 150_000},
    }
    used = 0
    candidates = []

    def add(kind, pk, data, *, at=None, file_ref=None, parent_id=None):
        nonlocal used
        source = {
            "id": f"{kind}:{pk}",
            "kind": kind,
            "record_id": str(pk),
            "data": data,
            "at": at.isoformat() if at else None,
            "parent_id": parent_id,
        }
        if file_ref:
            source["file_ref"] = file_ref
            source["file_version"] = file_ref.get("version", "")
        source["hash"] = digest({k: v for k, v in source.items() if k != "file_ref"})
        candidates.append(source)

    add(
        "project",
        project.pk,
        {
            "name": project.name,
            "address": project.address,
            "description": project.description[:4000],
            "company": project.workspace.name,
            "date_start": str(project.date_start),
            "date_end": str(project.date_end or ""),
            "context_declared_by_author": elaborato.context[:4000],
        },
    )
    add(
        "request",
        elaborato.pk,
        {
            "document_type": elaborato.document_type,
            "period_start": result["period_start"],
            "period_end": result["period_end"],
            "language": elaborato.language,
            "context": elaborato.context[:4000],
            "requested_by": profile_display_name(elaborato.created_by),
            "declared_parameters": True,
        },
        at=elaborato.created_at,
    )
    for declaration in declarations:
        add(
            "declaration",
            declaration["id"],
            {
                "text": declaration["text"],
                "declared_by": declaration["author"],
                "declared_at": declaration["at"],
                "nature": "reported",
                **({"document_field": declaration["field"]} if declaration.get("field") else {}),
            },
        )
    # Membership is NOT evidence of attendance at a meeting or on a given date.
    for member in (
        project.members.filter(status=ProjectMemberStatus.ACTIVE, disabled=False)
        .select_related("profile__workspace", "profile__user")
        .order_by("pk")[:101]
    ):
        add(
            "member",
            member.pk,
            {
                "name": profile_display_name(member.profile),
                "profile_id": member.profile_id,
                "role": member.role,
                "company": member.profile.workspace.name,
                "presence": "unknown",
                "professional_roles": member.project_role_codes,
            },
        )

    posts = list(
        project.posts.filter(is_deleted=False, published_date__gte=start, published_date__lt=end)
        .select_related("author", "task", "activity")
        .prefetch_related("attachments")
        .order_by("published_date", "pk")[:181]
    )
    if len(posts) > 180:
        result["truncated"] = True
    # Comments in the period can refer to a post created before the period.
    comments = list(
        PostComment.objects.filter(
            post__project=project,
            post__is_deleted=False,
            is_deleted=False,
            created_at__gte=start,
            created_at__lt=end,
        )
        .select_related("post__author", "post__task", "post__activity", "author")
        .order_by("created_at", "pk")[:201]
    )
    if len(comments) > 200:
        result["truncated"] = True
    by_id = {p.pk: p for p in posts[:180]}
    for comment in comments[:200]:
        by_id.setdefault(comment.post_id, comment.post)
    for post in sorted(by_id.values(), key=lambda p: (p.published_date, p.pk)):
        add(
            "post",
            post.pk,
            {
                "text": (post.original_text or post.text)[:8000],
                "author": profile_display_name(post.author),
                "post_kind": post.post_kind,
                "task": post.task.name if post.task else None,
                "activity": post.activity.title if post.activity else None,
                "alert": post.alert,
                "weather_recorded": post.weather_snapshot or {},
                "outside_period_context": not (start <= post.published_date < end),
            },
            at=post.published_date,
        )
        for attachment in post.attachments.order_by("pk")[:16]:
            filename = PurePosixPath(attachment.file.name).name
            image = attachment.content_type.startswith("image/") or PurePosixPath(
                filename
            ).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
            add(
                "image_attachment" if image else "attachment",
                attachment.pk,
                {
                    "filename": filename,
                    "context": (post.original_text or post.text)[:800],
                    "visual_content_verified": False,
                    "media_kind": "image"
                    if image
                    else "audio"
                    if PurePosixPath(filename).suffix.lower()
                    in {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".webm", ".mp4"}
                    else "file",
                    "event_date_from_parent": post.published_date.isoformat(),
                    "uploaded_at_is_not_event_date": True,
                },
                at=attachment.created_at,
                file_ref={
                    "model": "post_attachment",
                    "id": attachment.pk,
                    "version": file_version(attachment, "file"),
                },
                parent_id=f"post:{post.pk}",
            )
    for comment in comments[:200]:
        add(
            "comment",
            comment.pk,
            {
                "text": (comment.original_text or comment.text)[:6000],
                "author": profile_display_name(comment.author),
            },
            at=comment.created_at,
            parent_id=f"post:{comment.post_id}",
        )
    for attachment in (
        CommentAttachment.objects.filter(comment__in=comments[:200])
        .select_related("comment")
        .order_by("pk")[:60]
    ):
        filename = PurePosixPath(attachment.file.name).name
        image = PurePosixPath(filename).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        add(
            "image_attachment" if image else "attachment",
            f"comment-{attachment.pk}",
            {
                "filename": filename,
                "context": (attachment.comment.original_text or attachment.comment.text)[:800],
                "visual_content_verified": False,
                "media_kind": "image"
                if image
                else "audio"
                if PurePosixPath(filename).suffix.lower()
                in {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".webm"}
                else "file",
                "event_date_from_parent": attachment.comment.created_at.isoformat(),
                "uploaded_at_is_not_event_date": True,
            },
            at=attachment.created_at,
            parent_id=f"comment:{attachment.comment_id}",
            file_ref={
                "model": "comment_attachment",
                "id": attachment.pk,
                "version": file_version(attachment, "file"),
            },
        )
    for task in (
        project.tasks.filter(
            date_start__lte=elaborato.period_end, date_end__gte=elaborato.period_start
        )
        .select_related("assigned_company")
        .order_by("date_start", "pk")[:121]
    ):
        add(
            "task",
            task.pk,
            {
                "name": task.name,
                "note": task.note[:1500],
                "company": task.assigned_company.name if task.assigned_company else None,
                "scheduled_start": str(task.date_start),
                "scheduled_end": str(task.date_end),
                "progress_current_snapshot": task.progress,
                "snapshot_is_not_period_end_progress": True,
            },
            at=task.updated_at,
        )
    for activity in (
        ProjectActivity.objects.filter(
            task__project=project, datetime_start__lt=end, datetime_end__gte=start
        )
        .select_related("task")
        .order_by("datetime_start", "pk")[:101]
    ):
        add(
            "activity",
            activity.pk,
            {
                "task": activity.task.name,
                "title": activity.title,
                "description": activity.description[:1500],
                "note": activity.note[:1500],
                "status_current_snapshot": activity.status,
            },
            at=activity.updated_at,
        )
    for photo in ProjectPhoto.objects.filter(
        project=project, created_at__gte=start, created_at__lt=end
    ).order_by("created_at", "pk")[:61]:
        add(
            "photo",
            photo.pk,
            {
                "title": photo.title,
                "filename": PurePosixPath(photo.photo.name).name,
                "visual_content_verified": False,
                "at_is_upload_date": True,
            },
            at=photo.created_at,
            file_ref={
                "model": "project_photo",
                "id": photo.pk,
                "version": file_version(photo, "photo"),
            },
        )
    from .models import ElaboratoRevision

    # Published PDFs are derived outputs, even though Drive stores them as
    # ordinary project files. Feeding them back as primary extracted evidence
    # amplified AI statements and could exhaust the source budget before photos.
    derived_ids = ElaboratoRevision.objects.filter(
        elaborato__project=project, drive_document_id__isnull=False
    ).values("drive_document_id")
    documents = list(
        ProjectDocument.objects.filter(project=project)
        .exclude(pk__in=derived_ids)
        .order_by("-updated_at", "pk")[:61]
    )
    from .document_sources import document_excerpts

    excerpts = document_excerpts(project.pk, documents)
    for document in documents:
        add(
            "drawing" if document.document_kind == "drawing" else "document",
            document.pk,
            {
                "title": document.title,
                "description": document.description[:2000],
                "file_content_extracted": bool(excerpts.get(document.pk)),
                "excerpts": excerpts.get(document.pk, []),
                "extraction_is_partial": bool(excerpts.get(document.pk)),
            },
            at=document.updated_at,
            file_ref={
                "model": "document",
                "id": document.pk,
                "version": file_version(document, "document"),
            },
        )
    for pin in (
        ProjectDrawingPin.objects.filter(project=project, post_id__in=by_id)
        .select_related("drawing_document")
        .order_by("pk")[:81]
    ):
        add(
            "drawing_pin",
            pin.pk,
            {
                "drawing": pin.drawing_document.title,
                "drawing_id": pin.drawing_document_id,
                "code": pin.pin_code,
                "label": pin.label,
                "page": pin.page_number,
                "x": pin.x,
                "y": pin.y,
            },
            at=pin.created_at,
            parent_id=f"post:{pin.post_id}",
        )
    for event in ProjectOperationalEvent.objects.filter(
        project=project, occurred_at__gte=start, occurred_at__lt=end
    ).order_by("occurred_at", "pk")[:101]:
        # Only safe operational summaries; event payloads can hold redundant or
        # unrelated snapshots and are deliberately not dumped into the prompt.
        add(
            "event",
            event.pk,
            {
                "type": event.event_type,
                "post_id": event.post_id_snapshot,
                "task_id": event.task_id_snapshot,
                "document_id": event.document_id_snapshot,
            },
            at=event.occurred_at,
        )
    prior = (
        ElaboratoRevision.objects.filter(
            elaborato__project=project,
            state__in=("published", "signed"),
            elaborato__period_end__lte=elaborato.period_end,
        )
        .exclude(elaborato=elaborato)
        .select_related("elaborato")
        .order_by("-published_at")[:6]
    )
    for revision in prior:
        add(
            "previous_elaborato",
            revision.pk,
            {
                "title": revision.elaborato.title,
                "revision": revision.number,
                "period_start": str(revision.elaborato.period_start),
                "period_end": str(revision.elaborato.period_end),
                "summary": [c["text"] for c in editor_claims(revision.editor_doc)[:12]],
                "secondary_source": True,
            },
            at=revision.published_at,
        )
    # Preserve primary communications before the often numerous media/member
    # records. Previously attachments could exhaust the budget before decisions
    # in comments or extracted documents were even considered.
    priorities = {
        "project": 0,
        "request": 0,
        "declaration": 0,
        "post": 1,
        "comment": 2,
        "document": 3,
        "drawing_pin": 4,
        "photo": 5,
        "image_attachment": 5,
        "task": 6,
        "activity": 6,
        "drawing": 7,
        "member": 8,
        "attachment": 9,
        "event": 10,
        "previous_elaborato": 11,
    }
    for source in sorted(candidates, key=lambda s: priorities.get(s["kind"], 12)):
        size = len(str(source))
        if len(result["sources"]) >= 450 or used + size > 150_000:
            result["truncated"] = True
            continue
        used += size
        result["sources"].append(source)
    if not posts and not comments:
        dates = []
        for query in (
            project.posts.filter(is_deleted=False, published_date__lt=start).order_by(
                "-published_date"
            ),
            project.posts.filter(is_deleted=False, published_date__gte=end).order_by(
                "published_date"
            ),
        ):
            value = query.values_list("published_date", flat=True).first()
            if value:
                dates.append(timezone.localtime(value).date().isoformat())
        result["nearby_post_dates"] = sorted(set(dates))
    from .readiness import coverage_summary

    result["coverage"] = coverage_summary(result)
    result["bundle_hash"] = digest(result)
    return result


def resolve_evidence_file(*, profile, project_id, source):
    """Reauthorize every read; never fetch arbitrary URLs supplied by an editor."""
    get_project_for_profile(profile=profile, project_id=project_id)
    ref = source.get("file_ref", {})
    from edilcloud.modules.projects.models import PostAttachment

    lookups = {
        "post_attachment": (
            PostAttachment,
            {"post__project_id": project_id, "post__is_deleted": False},
            "file",
        ),
        "comment_attachment": (
            CommentAttachment,
            {
                "comment__post__project_id": project_id,
                "comment__post__is_deleted": False,
                "comment__is_deleted": False,
            },
            "file",
        ),
        "project_photo": (ProjectPhoto, {"project_id": project_id}, "photo"),
        "document": (ProjectDocument, {"project_id": project_id}, "document"),
    }
    if ref.get("model") not in lookups:
        raise ValueError("File non disponibile.")
    model, filters, field = lookups[ref["model"]]
    obj = model.objects.filter(pk=ref.get("id"), **filters).first()
    if not obj:
        raise ValueError("La fonte è stata rimossa o non è più accessibile.")
    if ref.get("version") and ref["version"] != file_version(obj, field):
        raise ValueError(
            "Il file della fonte è stato modificato. Aggiorna le fonti prima di generare il PDF."
        )
    return getattr(obj, field)
