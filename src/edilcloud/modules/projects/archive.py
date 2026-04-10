from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.http import FileResponse
from django.utils import timezone
from django.utils.text import slugify

from edilcloud.modules.projects.models import Project, ProjectStatus


def project_archive_policy() -> dict[str, int | str]:
    return {
        "archive_after_days": int(settings.PROJECT_ARCHIVE_AFTER_DAYS),
        "purge_after_archive_days": int(settings.PROJECT_PURGE_AFTER_ARCHIVE_DAYS),
        "export_format": "zip",
    }


def sync_project_archive_schedule(
    *,
    project: Project,
    reference_time=None,
    save: bool = True,
) -> Project:
    now = reference_time or timezone.now()
    changed_fields: list[str] = []

    if project.status != ProjectStatus.CLOSED:
        for field_name in (
            "closed_at",
            "archive_due_at",
            "archived_at",
            "purge_due_at",
        ):
            if getattr(project, field_name) is not None:
                setattr(project, field_name, None)
                changed_fields.append(field_name)
        if changed_fields and save:
            project.save(update_fields=[*changed_fields, "updated_at"])
        return project

    closed_at = project.closed_at or now
    archive_due_at = closed_at + timedelta(days=int(settings.PROJECT_ARCHIVE_AFTER_DAYS))
    purge_due_at = archive_due_at + timedelta(days=int(settings.PROJECT_PURGE_AFTER_ARCHIVE_DAYS))

    for field_name, next_value in (
        ("closed_at", closed_at),
        ("archive_due_at", archive_due_at),
        ("purge_due_at", purge_due_at),
    ):
        if getattr(project, field_name) != next_value:
            setattr(project, field_name, next_value)
            changed_fields.append(field_name)

    if changed_fields and save:
        project.save(update_fields=[*changed_fields, "updated_at"])
    return project


def mark_project_archived_if_due(
    *,
    project: Project,
    reference_time=None,
    save: bool = True,
) -> Project:
    now = reference_time or timezone.now()
    sync_project_archive_schedule(project=project, reference_time=now, save=save)
    if (
        project.status == ProjectStatus.CLOSED
        and project.archive_due_at is not None
        and project.archived_at is None
        and now >= project.archive_due_at
    ):
        project.archived_at = now
        if save:
            project.save(update_fields=["archived_at", "updated_at"])
    return project


def process_project_archive_lifecycle(*, reference_time=None, delete_ready: bool = False) -> dict[str, Any]:
    now = reference_time or timezone.now()
    archived_count = 0
    ready_to_delete_ids: list[int] = []
    pending_owner_export_ids: list[int] = []
    deleted_ids: list[int] = []

    projects = list(Project.objects.filter(status=ProjectStatus.CLOSED).order_by("id"))
    for project in projects:
        previous_archived_at = project.archived_at
        sync_project_archive_schedule(project=project, reference_time=now, save=True)
        mark_project_archived_if_due(project=project, reference_time=now, save=True)
        if previous_archived_at is None and project.archived_at is not None:
            archived_count += 1

        if project.purge_due_at is None or now < project.purge_due_at:
            continue

        if project.owner_export_sent_at is None:
            pending_owner_export_ids.append(project.id)
            continue

        ready_to_delete_ids.append(project.id)
        if delete_ready:
            project.delete()
            deleted_ids.append(project.id)

    return {
        "scanned": len(projects),
        "archived": archived_count,
        "ready_to_delete_ids": ready_to_delete_ids,
        "pending_owner_export_ids": pending_owner_export_ids,
        "deleted_ids": deleted_ids,
    }


def _safe_file_name(value: str | None, *, fallback: str) -> str:
    candidate = Path(value or "").name.strip()
    if not candidate:
        candidate = fallback
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", candidate).strip(".-")
    return sanitized or fallback


def _safe_relative_parts(value: str | None) -> list[str]:
    if not value:
        return []
    normalized = str(value).replace("\\", "/")
    return [
        slugify(part.strip()) or f"segment-{index + 1}"
        for index, part in enumerate(normalized.split("/"))
        if part.strip()
    ]


def _write_json(zip_file: zipfile.ZipFile, archive_path: str, payload: Any) -> None:
    zip_file.writestr(
        archive_path,
        json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2),
    )


def _write_file_field(zip_file: zipfile.ZipFile, archive_path: str, file_field) -> None:
    if not file_field or not getattr(file_field, "name", ""):
        return
    try:
        file_field.open("rb")
    except Exception:
        return
    try:
        zip_file.writestr(archive_path, file_field.read())
    finally:
        try:
            file_field.close()
        except Exception:
            pass


def export_project_archive(*, profile, project_id: int):
    from edilcloud.modules.projects.services import (
        annotate_posts_with_feed_activity,
        get_project_overview,
        get_project_with_team_context,
        list_project_folders,
        list_project_gantt,
        project_company_colors_for_context,
        project_posts_queryset,
        project_tasks_queryset,
        serialize_post,
    )

    now = timezone.now()
    project, membership, members = get_project_with_team_context(
        profile=profile,
        project_id=project_id,
    )
    sync_project_archive_schedule(project=project, reference_time=now, save=True)
    mark_project_archived_if_due(project=project, reference_time=now, save=True)

    tasks = list(project_tasks_queryset(project))
    company_colors_by_workspace_id = project_company_colors_for_context(
        project=project,
        members=members,
        tasks=tasks,
    )
    overview = get_project_overview(profile=profile, project_id=project_id)
    gantt = list_project_gantt(profile=profile, project_id=project_id)
    folders = list_project_folders(profile=profile, project_id=project_id)
    invite_codes = list(project.invite_codes.order_by("-created_at", "-id"))
    operational_events = list(project.operational_events.order_by("-occurred_at", "-id"))
    posts = list(
        annotate_posts_with_feed_activity(project_posts_queryset())
        .filter(project=project)
        .order_by("-effective_last_activity_at", "-id")
    )
    serialized_posts = [
        serialize_post(
            post=post,
            membership=membership,
            viewer_profile=profile,
            effective_last_activity_at=getattr(post, "effective_last_activity_at", None),
            company_colors_by_workspace_id=company_colors_by_workspace_id,
        )
        for post in posts
    ]

    archive_file = tempfile.SpooledTemporaryFile(max_size=25 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(
        archive_file,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as zip_file:
        _write_json(
            zip_file,
            "manifest/project.json",
            {
                "project": {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description or None,
                    "status": project.status,
                    "date_start": project.date_start,
                    "date_end": project.date_end,
                    "closed_at": project.closed_at,
                    "archive_due_at": project.archive_due_at,
                    "archived_at": project.archived_at,
                    "purge_due_at": project.purge_due_at,
                    "last_export_at": project.last_export_at,
                    "owner_export_sent_at": project.owner_export_sent_at,
                },
                "workspace": {
                    "id": project.workspace_id,
                    "name": project.workspace.name,
                    "slug": project.workspace.slug or None,
                },
                "generated_at": now,
                "generated_by_profile_id": profile.id,
            },
        )
        _write_json(
            zip_file,
            "manifest/retention-policy.json",
            {
                **project_archive_policy(),
                "closed_at": project.closed_at,
                "archive_due_at": project.archive_due_at,
                "archived_at": project.archived_at,
                "purge_due_at": project.purge_due_at,
                "owner_export_sent_at": project.owner_export_sent_at,
                "note": (
                    "Il progetto resta conservato dopo la chiusura. "
                    "Prima della cancellazione definitiva e richiesta la consegna del pacchetto ai possessori."
                ),
            },
        )
        _write_json(
            zip_file,
            "manifest/contents.json",
            {
                "team_members": len(overview["team"]),
                "tasks": len(overview["tasks"]),
                "documents": len(overview["documents"]),
                "photos": len(overview["photos"]),
                "posts": len(serialized_posts),
                "invite_codes": len(invite_codes),
                "operational_events": len(operational_events),
            },
        )
        _write_json(zip_file, "team/members.json", overview["team"])
        _write_json(
            zip_file,
            "team/invite-codes.json",
            [
                {
                    "id": invite.id,
                    "email": invite.email,
                    "status": invite.status,
                    "unique_code": invite.unique_code,
                    "expires_at": invite.expires_at,
                    "accepted_at": invite.accepted_at,
                    "created_at": invite.created_at,
                }
                for invite in invite_codes
            ],
        )
        _write_json(zip_file, "planning/tasks.json", overview["tasks"])
        _write_json(zip_file, "planning/gantt.json", gantt)
        _write_json(zip_file, "documents/folders.json", folders)
        _write_json(zip_file, "documents/documents.json", overview["documents"])
        _write_json(zip_file, "photos/photos.json", overview["photos"])
        _write_json(zip_file, "threads/posts-full.json", serialized_posts)
        _write_json(zip_file, "threads/alert-posts.json", overview["alertPosts"])
        _write_json(zip_file, "threads/recent-posts.json", overview["recentPosts"])
        _write_json(
            zip_file,
            "operations/events.json",
            [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "occurred_at": event.occurred_at,
                    "task_id_snapshot": event.task_id_snapshot,
                    "activity_id_snapshot": event.activity_id_snapshot,
                    "post_id_snapshot": event.post_id_snapshot,
                    "comment_id_snapshot": event.comment_id_snapshot,
                    "folder_id_snapshot": event.folder_id_snapshot,
                    "document_id_snapshot": event.document_id_snapshot,
                    "photo_id_snapshot": event.photo_id_snapshot,
                    "member_id_snapshot": event.member_id_snapshot,
                    "invite_id_snapshot": event.invite_id_snapshot,
                    "actor_profile_id_snapshot": event.actor_profile_id_snapshot,
                    "payload": event.payload,
                }
                for event in operational_events
            ],
        )

        if project.logo:
            logo_name = _safe_file_name(project.logo.name, fallback=f"project-{project.id}-logo")
            _write_file_field(zip_file, f"project/files/{logo_name}", project.logo)

        for document in project.documents.select_related("folder").order_by("-updated_at", "-id"):
            original_name = Path(document.document.name).name if document.document else document.title
            file_name = _safe_file_name(
                original_name,
                fallback=f"document-{document.id}",
            )
            folder_parts = _safe_relative_parts(document.folder.path if document.folder else "")
            archive_path = "/".join(
                ["documents", "files", *folder_parts, f"{document.id}-{file_name}"]
            )
            _write_file_field(zip_file, archive_path, document.document)

        for photo in project.photos.order_by("-created_at", "-id"):
            original_name = Path(photo.photo.name).name if photo.photo else photo.title
            file_name = _safe_file_name(original_name, fallback=f"photo-{photo.id}")
            _write_file_field(zip_file, f"photos/files/{photo.id}-{file_name}", photo.photo)

        for post in posts:
            for attachment in post.attachments.all():
                file_name = _safe_file_name(
                    attachment.file.name,
                    fallback=f"post-attachment-{attachment.id}",
                )
                _write_file_field(
                    zip_file,
                    f"threads/post-attachments/post-{post.id}/{attachment.id}-{file_name}",
                    attachment.file,
                )
            for comment in post.comments.all():
                for attachment in comment.attachments.all():
                    file_name = _safe_file_name(
                        attachment.file.name,
                        fallback=f"comment-attachment-{attachment.id}",
                    )
                    _write_file_field(
                        zip_file,
                        (
                            f"threads/comment-attachments/post-{post.id}/comment-{comment.id}/"
                            f"{attachment.id}-{file_name}"
                        ),
                        attachment.file,
                    )

    project.last_export_at = now
    project.save(update_fields=["last_export_at", "updated_at"])
    archive_file.seek(0)
    filename = f"edilcloud-project-{project.id}-{slugify(project.name) or 'project'}.zip"
    return FileResponse(
        archive_file,
        as_attachment=True,
        filename=filename,
        content_type="application/zip",
    )
