from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from django.utils import timezone

from edilcloud.modules.projects.demo_master_assets import BACKEND_ROOT, DEMO_ASSET_SOURCE_ROOT
from edilcloud.modules.projects.management.commands.seed_rich_demo_project import (
    COMPANIES,
    DEMO_TARGET_PROGRESS,
    DOCUMENTS,
    PHOTOS,
    PROJECT_BLUEPRINT,
    TASKS,
    THREAD_COMMUNICATIONS,
)
from edilcloud.modules.projects.models import (
    CommentAttachment,
    DemoProjectSnapshotValidationStatus,
    PostAttachment,
    PostComment,
    PostKind,
    Project,
    ProjectActivity,
    ProjectDocument,
    ProjectMember,
    ProjectMemberStatus,
    ProjectPhoto,
    ProjectPost,
    ProjectTask,
)
from edilcloud.modules.projects.services import calculate_project_progress
from edilcloud.modules.workspaces.services import file_url


DEMO_SNAPSHOT_SCHEMA_VERSION = 1
DEMO_SNAPSHOT_EXPORT_ROOT = BACKEND_ROOT / "demo-assets" / "demo-master" / "snapshots"
DEMO_ASSET_MANIFEST_PATH = BACKEND_ROOT / "docs" / "DEMO_ASSET_PIN_MANIFEST.md"


def normalize_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    return str(value).replace("\\", "/")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(json.dumps(value, ensure_ascii=True, sort_keys=True, default=str))


def serialize_snapshot_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def build_seed_hash() -> str:
    payload = {
        "project_blueprint": PROJECT_BLUEPRINT,
        "target_progress": DEMO_TARGET_PROGRESS,
        "companies": COMPANIES,
        "documents": DOCUMENTS,
        "photos": PHOTOS,
        "tasks": TASKS,
        "thread_communications": THREAD_COMMUNICATIONS,
    }
    return sha256_json(payload)


def build_asset_manifest_hash() -> str:
    manifest_body = DEMO_ASSET_MANIFEST_PATH.read_text(encoding="utf-8") if DEMO_ASSET_MANIFEST_PATH.exists() else ""
    source_files: list[dict[str, Any]] = []
    if DEMO_ASSET_SOURCE_ROOT.exists():
        for path in sorted(item for item in DEMO_ASSET_SOURCE_ROOT.rglob("*") if item.is_file()):
            source_files.append(
                {
                    "path": normalize_path(path.relative_to(BACKEND_ROOT)),
                    "size": path.stat().st_size,
                    "content_hash": sha256_bytes(path.read_bytes()),
                }
            )
    payload = {
        "manifest_hash": sha256_text(manifest_body),
        "source_files": source_files,
    }
    return sha256_json(payload)


def build_demo_snapshot_payload(*, project: Project, business_date) -> dict[str, Any]:
    members = list(
        ProjectMember.objects.select_related("profile", "profile__workspace", "profile__user")
        .filter(project=project, status=ProjectMemberStatus.ACTIVE, disabled=False)
        .order_by("profile__workspace__name", "profile__first_name", "profile__last_name", "id")
    )
    tasks = list(
        ProjectTask.objects.select_related("assigned_company")
        .filter(project=project)
        .prefetch_related("activities__workers")
        .order_by("date_start", "id")
    )
    documents = list(
        ProjectDocument.objects.select_related("folder").filter(project=project).order_by("title", "id")
    )
    photos = list(ProjectPhoto.objects.filter(project=project).order_by("title", "id"))
    posts = list(
        ProjectPost.objects.select_related("task", "activity", "author", "author__workspace")
        .filter(project=project, is_deleted=False)
        .order_by("published_date", "id")
    )
    post_ids = [post.id for post in posts]
    comments = list(
        PostComment.objects.select_related("author", "author__workspace", "post")
        .filter(post_id__in=post_ids, is_deleted=False)
        .order_by("created_at", "id")
    )
    post_attachments = list(PostAttachment.objects.select_related("post").filter(post_id__in=post_ids).order_by("id"))
    comment_ids = [comment.id for comment in comments]
    comment_attachments = list(
        CommentAttachment.objects.select_related("comment")
        .filter(comment_id__in=comment_ids)
        .order_by("id")
    )

    progress = calculate_project_progress(project)
    summary = {
        "project_id": project.id,
        "name": project.name,
        "description": project.description or None,
        "address": project.address or None,
        "google_place_id": project.google_place_id or None,
        "latitude": project.latitude,
        "longitude": project.longitude,
        "date_start": serialize_snapshot_value(project.date_start),
        "date_end": serialize_snapshot_value(project.date_end),
        "status": project.status,
        "progress_percentage": progress,
        "is_demo_master": project.is_demo_master,
        "demo_snapshot_version": project.demo_snapshot_version or None,
        "business_date": serialize_snapshot_value(business_date),
    }
    stats = {
        "members": len(members),
        "tasks": len(tasks),
        "activities": sum(task.activities.count() for task in tasks),
        "documents": len(documents),
        "photos": len(photos),
        "posts": len(posts),
        "comments": len(comments),
        "post_attachments": len(post_attachments),
        "comment_attachments": len(comment_attachments),
        "open_issues": sum(1 for post in posts if post.post_kind == PostKind.ISSUE and post.alert),
        "resolved_issues": sum(1 for post in posts if post.post_kind == PostKind.ISSUE and not post.alert),
    }
    return {
        "schema_version": DEMO_SNAPSHOT_SCHEMA_VERSION,
        "business_date": serialize_snapshot_value(business_date),
        "project": summary,
        "stats": stats,
        "members": [
            {
                "id": member.id,
                "profile_id": member.profile_id,
                "name": member.profile.member_name,
                "email": member.profile.email,
                "workspace": member.profile.workspace.name,
                "workspace_slug": member.profile.workspace.slug,
                "workspace_logo": normalize_path(getattr(member.profile.workspace.logo, "name", None)),
                "profile_photo": normalize_path(getattr(member.profile.photo, "name", None)),
                "role": member.role,
                "project_role_codes": list(member.project_role_codes or []),
                "is_external": member.is_external,
            }
            for member in members
        ],
        "tasks": [
            {
                "id": task.id,
                "name": task.name,
                "assigned_company": task.assigned_company.name if task.assigned_company else None,
                "date_start": serialize_snapshot_value(task.date_start),
                "date_end": serialize_snapshot_value(task.date_end),
                "date_completed": serialize_snapshot_value(task.date_completed),
                "progress": task.progress,
                "alert": task.alert,
                "starred": task.starred,
                "note": task.note or None,
                "activities": [
                    {
                        "id": activity.id,
                        "title": activity.title,
                        "status": activity.status,
                        "progress": activity.progress,
                        "datetime_start": serialize_snapshot_value(activity.datetime_start),
                        "datetime_end": serialize_snapshot_value(activity.datetime_end),
                        "alert": activity.alert,
                        "starred": activity.starred,
                        "note": activity.note or None,
                        "workers": [worker.member_name for worker in activity.workers.all()],
                    }
                    for activity in task.activities.all().order_by("datetime_start", "id")
                ],
            }
            for task in tasks
        ],
        "documents": [
            {
                "id": document.id,
                "title": document.title,
                "folder": document.folder.path if document.folder else None,
                "relative_path": normalize_path(getattr(document.document, "name", None)),
                "url": file_url(document.document),
            }
            for document in documents
        ],
        "photos": [
            {
                "id": photo.id,
                "title": photo.title,
                "relative_path": normalize_path(getattr(photo.photo, "name", None)),
                "url": file_url(photo.photo),
            }
            for photo in photos
        ],
        "posts": [
            {
                "id": post.id,
                "task_id": post.task_id,
                "activity_id": post.activity_id,
                "post_kind": post.post_kind,
                "alert": post.alert,
                "is_public": post.is_public,
                "author": post.author.member_name,
                "author_workspace": post.author.workspace.name,
                "published_date": serialize_snapshot_value(post.published_date),
                "text": post.text,
            }
            for post in posts
        ],
        "comments": [
            {
                "id": comment.id,
                "post_id": comment.post_id,
                "parent_id": comment.parent_id,
                "author": comment.author.member_name,
                "author_workspace": comment.author.workspace.name,
                "created_at": serialize_snapshot_value(comment.created_at),
                "text": comment.text,
            }
            for comment in comments
        ],
        "attachments": {
            "post": [
                {
                    "id": attachment.id,
                    "post_id": attachment.post_id,
                    "relative_path": normalize_path(getattr(attachment.file, "name", None)),
                    "url": file_url(attachment.file),
                }
                for attachment in post_attachments
            ],
            "comment": [
                {
                    "id": attachment.id,
                    "comment_id": attachment.comment_id,
                    "relative_path": normalize_path(getattr(attachment.file, "name", None)),
                    "url": file_url(attachment.file),
                }
                for attachment in comment_attachments
            ],
        },
    }


def build_demo_snapshot_record(
    *,
    project: Project,
    version: str,
    business_date,
    notes: str = "",
    validation_status: str = DemoProjectSnapshotValidationStatus.DRAFT,
    active_in_production: bool = False,
    export_relative_path: str = "",
) -> dict[str, Any]:
    payload = build_demo_snapshot_payload(project=project, business_date=business_date)
    return {
        "version": version,
        "name": project.name,
        "business_date": business_date,
        "schema_version": DEMO_SNAPSHOT_SCHEMA_VERSION,
        "seed_hash": build_seed_hash(),
        "asset_manifest_hash": build_asset_manifest_hash(),
        "payload_hash": sha256_json(payload),
        "validation_status": validation_status,
        "validated_at": timezone.now() if validation_status == DemoProjectSnapshotValidationStatus.VALIDATED else None,
        "active_in_production": active_in_production,
        "notes": notes,
        "export_relative_path": export_relative_path,
        "payload": payload,
    }
