from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from django.conf import settings


def _file_url(file_field) -> str | None:
    if not file_field:
        return None
    try:
        url = file_field.url
    except ValueError:
        return None
    if str(url).startswith("http://") or str(url).startswith("https://"):
        return str(url)
    base_url = str(getattr(settings, "BACKEND_PUBLIC_URL", "") or "").rstrip("/")
    if base_url and str(url).startswith("/"):
        return f"{base_url}{url}"
    return str(url)


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return ""


def _display_name(profile) -> str:
    member_name = str(getattr(profile, "member_name", "") or "").strip()
    if member_name:
        return member_name
    first_name = str(getattr(profile, "first_name", "") or "").strip()
    last_name = str(getattr(profile, "last_name", "") or "").strip()
    full_name = f"{first_name} {last_name}".strip()
    if full_name:
        return full_name
    return str(getattr(profile, "email", "") or "").strip()


def _profile_photo_url(profile) -> str:
    return _first_non_empty(
        _file_url(getattr(profile, "photo", None)),
        _file_url(getattr(getattr(profile, "user", None), "photo", None)),
    )


def _project_image_url(project, inviter_profile) -> str:
    return _first_non_empty(
        _file_url(getattr(project, "logo", None)),
        _file_url(getattr(getattr(project, "workspace", None), "logo", None)),
        _profile_photo_url(inviter_profile),
    )


def _workspace_image_url(workspace, inviter_profile) -> str:
    return _first_non_empty(
        _file_url(getattr(workspace, "logo", None)),
        _profile_photo_url(inviter_profile),
    )


def _attachment_extension(file_field) -> str:
    return Path(getattr(file_field, "name", "") or "").suffix.lower().lstrip(".")


def _is_visual_attachment(file_field) -> bool:
    return _attachment_extension(file_field) in {
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
        "bmp",
        "tif",
        "tiff",
        "heic",
        "avif",
    }


def _iter_related_items(value) -> list[Any]:
    if value is None:
        return []
    if hasattr(value, "all"):
        return list(value.all())
    if isinstance(value, list):
        return value
    return list(value)


def _first_visual_media_url(*, attachments=None, file_field=None) -> str:
    if file_field is not None and _is_visual_attachment(file_field):
        return _file_url(file_field) or ""
    for attachment in _iter_related_items(attachments):
        media_file = getattr(attachment, "file", None)
        if media_file is not None and _is_visual_attachment(media_file):
            return _file_url(media_file) or ""
    return ""


def _project_context_image_url(*, project=None, workspace=None, actor_profile=None, attachments=None, file_field=None) -> str:
    project_workspace = getattr(project, "workspace", None)
    actor_workspace = getattr(actor_profile, "workspace", None)
    return _first_non_empty(
        _first_visual_media_url(attachments=attachments, file_field=file_field),
        _file_url(getattr(project, "logo", None)),
        _file_url(getattr(workspace, "logo", None)),
        _file_url(getattr(project_workspace, "logo", None)),
        _profile_photo_url(actor_profile),
        _file_url(getattr(actor_workspace, "logo", None)),
    )


def _format_date_label(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    return str(value)


def _activity_status_label(status: str | None) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "to-do":
        return "da fare"
    if normalized == "progress":
        return "in corso"
    if normalized == "completed":
        return "completata"
    return normalized or "aggiornata"


def _thread_location_label(post) -> str:
    activity = getattr(post, "activity", None)
    task = getattr(post, "task", None)
    project = getattr(post, "project", None)
    if activity is not None and getattr(activity, "title", None):
        return f"Attivita {activity.title}"
    if task is not None and getattr(task, "name", None):
        return f"Task {task.name}"
    return f"Progetto {getattr(project, 'name', '')}".strip()


def _snippet_body(*, location_label: str, snippet: str) -> str:
    normalized_snippet = str(snippet or "").strip()
    if normalized_snippet:
        return f'{location_label} · "{normalized_snippet}"'
    return location_label


def _folder_location_label(*, project_name: str, folder_path: str) -> str:
    normalized_path = str(folder_path or "").strip()
    if "/" in normalized_path:
        return f"In {normalized_path.rsplit('/', 1)[0]}"
    return f"Progetto {project_name}"


def _document_location_label(*, project_name: str, folder_path: str | None) -> str:
    normalized_path = str(folder_path or "").strip()
    if normalized_path:
        return f"Cartella {normalized_path}"
    return f"Progetto {project_name}"


@dataclass(frozen=True)
class NotificationBlueprint:
    kind: str
    subject: str
    body: str = ""
    content_type: str = ""
    object_id: int | None = None
    project_id: int | None = None
    task_id: int | None = None
    activity_id: int | None = None
    post_id: int | None = None
    comment_id: int | None = None
    folder_id: int | None = None
    document_id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


def build_project_invite_notification(*, invite, inviter_profile) -> NotificationBlueprint:
    project = invite.project
    inviter_name = inviter_profile.member_name
    image_url = _project_image_url(project, inviter_profile)
    return NotificationBlueprint(
        kind="project.invite.created",
        subject=f"Invito al cantiere {project.name}",
        body=(
            f"{inviter_name} ti ha invitato nel cantiere. "
            "Apri EdilCloud per vedere l'invito e accedere al progetto dopo l'accettazione."
        ),
        content_type="project_invite",
        object_id=invite.id,
        data={
            "category": "team",
            "action": "invite_created",
            "invite_scope": "project",
            "project_name": project.name,
            "project_id": project.id,
            "invite_email": invite.email,
            "invite_code": invite.unique_code,
            "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
            "image_url": image_url,
        },
    )


def build_workspace_invite_notification(*, invite, inviter_profile) -> NotificationBlueprint:
    workspace = invite.workspace
    inviter_name = inviter_profile.member_name
    image_url = _workspace_image_url(workspace, inviter_profile)
    role_label = invite.get_role_display()
    return NotificationBlueprint(
        kind="workspace.invite.created",
        subject=f"Invito nel workspace {workspace.name}",
        body=(
            f"{inviter_name} ti ha invitato come {role_label}. "
            "Apri EdilCloud per vedere l'invito e completare l'accesso."
        ),
        content_type="workspace_invite",
        object_id=invite.id,
        data={
            "category": "workspace",
            "action": "invite_created",
            "invite_scope": "workspace",
            "workspace_id": workspace.id,
            "workspace_name": workspace.name,
            "invite_email": invite.email,
            "invite_code": invite.invite_code,
            "invite_uidb36": invite.uidb36,
            "invite_token": invite.token,
            "role": invite.role,
            "role_label": role_label,
            "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
            "image_url": image_url,
        },
    )


def build_project_member_added_notification(*, project, member, target_profile, actor_profile, role_label: str) -> NotificationBlueprint:
    image_url = _project_context_image_url(
        project=project,
        workspace=getattr(target_profile, "workspace", None),
        actor_profile=actor_profile,
    )
    return NotificationBlueprint(
        kind="project.member.added",
        subject=f"{_display_name(actor_profile)} ti ha aggiunto al cantiere {project.name}",
        body=f"Ruolo nel progetto: {role_label}.",
        content_type="team",
        object_id=getattr(member, "id", None),
        project_id=project.id,
        data={
            "category": "team",
            "action": "added",
            "target_tab": "team",
            "project_name": project.name,
            "member_role": role_label,
            "member_company_name": getattr(getattr(target_profile, "workspace", None), "name", None),
            "image_url": image_url,
        },
    )


def build_project_task_notification(*, task, actor_profile, action: str, audience: str) -> NotificationBlueprint:
    project = task.project
    actor_name = _display_name(actor_profile)
    image_url = _project_context_image_url(
        project=project,
        workspace=getattr(task, "assigned_company", None),
        actor_profile=actor_profile,
    )
    if audience == "assigned":
        subject = (
            f"Nuovo task per la tua azienda: {task.name}"
            if action == "created"
            else f"{actor_name} ha assegnato {task.name} alla tua azienda"
        )
        body = (
            f"{project.name} · dal {_format_date_label(task.date_start)} al {_format_date_label(task.date_end)}"
            if action == "created"
            else f"{project.name} · avanzamento {int(getattr(task, 'progress', 0) or 0)}%"
        )
        kind = "project.task.assigned"
    else:
        subject = (
            f"{actor_name} ha creato il task {task.name}"
            if action == "created"
            else f"{actor_name} ha aggiornato il task {task.name}"
        )
        body = f"{project.name} · avanzamento {int(getattr(task, 'progress', 0) or 0)}%"
        if action == "updated" and bool(getattr(task, "alert", False)):
            body = f"{body} · in alert"
        kind = f"project.task.{action}"
    return NotificationBlueprint(
        kind=kind,
        subject=subject,
        body=body,
        content_type="task",
        object_id=task.id,
        project_id=project.id,
        task_id=task.id,
        data={
            "category": "task",
            "action": action if audience != "assigned" else "assigned",
            "target_tab": "task",
            "task_name": task.name,
            "project_name": project.name,
            "progress": int(getattr(task, "progress", 0) or 0),
            "alert": bool(getattr(task, "alert", False)),
            "assigned_company_name": getattr(getattr(task, "assigned_company", None), "name", None),
            "image_url": image_url,
        },
    )


def build_project_activity_notification(*, activity, actor_profile, action: str, audience: str) -> NotificationBlueprint:
    task = activity.task
    project = task.project
    actor_name = _display_name(actor_profile)
    image_url = _project_context_image_url(project=project, actor_profile=actor_profile)
    status_label = _activity_status_label(getattr(activity, "status", ""))
    if audience == "assigned":
        subject = (
            f"{actor_name} ti ha assegnato l'attivita {activity.title}"
            if action == "created"
            else f"{actor_name} ti ha coinvolto nell'attivita {activity.title}"
        )
        body = f"{task.name} · {status_label}"
        kind = "project.activity.assigned"
    else:
        subject = (
            f"{actor_name} ha creato l'attivita {activity.title}"
            if action == "created"
            else f"{actor_name} ha aggiornato l'attivita {activity.title}"
        )
        body = f"{task.name} · stato {status_label}"
        if action == "updated" and bool(getattr(activity, "alert", False)):
            body = f"{body} · in alert"
        kind = f"project.activity.{action}"
    return NotificationBlueprint(
        kind=kind,
        subject=subject,
        body=body,
        content_type="activity",
        object_id=activity.id,
        project_id=project.id,
        task_id=task.id,
        activity_id=activity.id,
        data={
            "category": "activity",
            "action": action if audience != "assigned" else "assigned",
            "target_tab": "task",
            "task_name": task.name,
            "activity_title": activity.title,
            "project_name": project.name,
            "status": getattr(activity, "status", ""),
            "progress": int(getattr(activity, "progress", 0) or 0),
            "alert": bool(getattr(activity, "alert", False)),
            "image_url": image_url,
        },
    )


def build_project_thread_notification(
    *,
    kind: str,
    subject: str,
    actor_profile,
    post,
    category: str,
    action: str,
    comment=None,
    snippet: str = "",
    extra: dict[str, Any] | None = None,
) -> NotificationBlueprint:
    location_label = _thread_location_label(post)
    image_url = _project_context_image_url(
        project=post.project,
        actor_profile=actor_profile,
        attachments=getattr(post, "attachments", None),
    )
    data = {
        "category": category,
        "action": action,
        "target_tab": "task",
        "project_name": post.project.name,
        "task_name": post.task.name if post.task_id and post.task else None,
        "activity_title": post.activity.title if post.activity_id and post.activity else None,
        "location_label": location_label,
        "snippet": str(snippet or "").strip() or None,
        "image_url": image_url,
    }
    if comment is not None:
        data["comment_id"] = comment.id
    if extra:
        data.update(extra)
    return NotificationBlueprint(
        kind=kind,
        subject=subject,
        body=_snippet_body(location_label=location_label, snippet=snippet),
        content_type="comment" if comment is not None else "post",
        object_id=comment.id if comment is not None else post.id,
        project_id=post.project_id,
        task_id=post.task_id,
        activity_id=post.activity_id,
        post_id=post.id,
        comment_id=comment.id if comment is not None else None,
        data=data,
    )


def build_project_folder_notification(
    *,
    kind: str,
    action: str,
    actor_profile,
    project,
    folder_id: int,
    folder_name: str,
    folder_path: str,
) -> NotificationBlueprint:
    actor_name = _display_name(actor_profile)
    image_url = _project_context_image_url(project=project, actor_profile=actor_profile)
    action_verb = {
        "created": "ha creato",
        "updated": "ha aggiornato",
        "deleted": "ha rimosso",
    }.get(action, "ha aggiornato")
    body = (
        f"Progetto {project.name}"
        if action == "deleted"
        else _folder_location_label(project_name=project.name, folder_path=folder_path)
    )
    return NotificationBlueprint(
        kind=kind,
        subject=f"{actor_name} {action_verb} la cartella {folder_name}",
        body=body,
        content_type="folder",
        object_id=folder_id,
        project_id=project.id,
        folder_id=folder_id,
        data={
            "category": "document",
            "action": action,
            "target_tab": "documenti",
            "target_doc": f"folder:{folder_id}",
            "folder_name": folder_name,
            "path": folder_path,
            "project_name": project.name,
            "image_url": image_url,
        },
    )


def build_project_document_notification(
    *,
    kind: str,
    action: str,
    actor_profile,
    project,
    document_id: int,
    document_title: str,
    folder_id: int | None = None,
    folder_path: str | None = None,
    file_field=None,
) -> NotificationBlueprint:
    actor_name = _display_name(actor_profile)
    image_url = _project_context_image_url(
        project=project,
        actor_profile=actor_profile,
        file_field=file_field,
    )
    action_verb = {
        "created": "ha caricato",
        "updated": "ha aggiornato",
        "deleted": "ha rimosso",
    }.get(action, "ha aggiornato")
    body = (
        f"Progetto {project.name}"
        if action == "deleted"
        else _document_location_label(project_name=project.name, folder_path=folder_path)
    )
    return NotificationBlueprint(
        kind=kind,
        subject=f"{actor_name} {action_verb} il documento {document_title}",
        body=body,
        content_type="document",
        object_id=document_id,
        project_id=project.id,
        folder_id=folder_id,
        document_id=document_id,
        data={
            "category": "document",
            "action": action,
            "target_tab": "documenti",
            "target_doc": f"document:{document_id}",
            "document_title": document_title,
            "folder_id": folder_id,
            "folder_path": folder_path,
            "project_name": project.name,
            "image_url": image_url,
        },
    )
