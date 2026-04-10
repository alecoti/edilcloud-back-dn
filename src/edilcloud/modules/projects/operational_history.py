from __future__ import annotations

from datetime import date, datetime
from typing import Any

from django.db.models import Q
from django.utils import timezone

from edilcloud.modules.projects.models import ProjectOperationalEvent


def _clean_text(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ").strip()


def _excerpt(value: Any, *, fallback: str, limit: int = 180) -> str:
    normalized = _clean_text(value)
    if not normalized:
        return fallback
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _bool_label(value: Any) -> str:
    return "Si" if bool(value) else "No"


def _status_label(value: Any) -> str:
    lowered = _clean_text(value).lower()
    if lowered == "to-do":
        return "Da fare"
    if lowered == "progress":
        return "In corso"
    if lowered == "completed":
        return "Completata"
    return lowered or "-"


def _post_kind_label(value: Any) -> str:
    lowered = _clean_text(value).lower()
    if lowered == "issue":
        return "Segnalazione"
    if lowered == "documentation":
        return "Documentazione"
    if lowered == "work-progress":
        return "Avanzamento"
    return lowered or "Post"


def _build_searchable_text(parts: list[Any]) -> str:
    return " ".join(_clean_text(part) for part in parts if _clean_text(part))


def _detail(label: str, value: Any, *, tone: str = "neutral") -> dict[str, str] | None:
    normalized = _clean_text(value)
    if not normalized:
        return None
    return {
        "label": label,
        "value": normalized,
        "tone": tone,
    }


def _change_details(changes: Any) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    if not isinstance(changes, list):
        return details

    for change in changes:
        if not isinstance(change, dict):
            continue
        label = _clean_text(change.get("label") or change.get("field"))
        if not label:
            continue
        value = _clean_text(change.get("value"))
        before = _clean_text(change.get("before"))
        after = _clean_text(change.get("after"))
        rendered = value
        if not rendered and (before or after):
            rendered = f"{before or '-'} -> {after or '-'}"
        if not rendered:
            continue
        details.append(
            {
                "label": label,
                "value": rendered,
                "tone": _clean_text(change.get("tone")) or "neutral",
            }
        )
    return details


def _timeline_scope(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    task_id = payload.get("taskId")
    activity_id = payload.get("activityId")
    project_name = _clean_text(data.get("project_name")) or "Progetto"
    task_name = _clean_text(data.get("task_name")) or project_name
    activity_title = _clean_text(data.get("activity_title")) or "Generale"
    project_level = bool(data.get("project_level")) or (task_id is None and activity_id is None)

    if activity_id:
        scope_kind = "activity"
        scope_label = activity_title
    elif project_level:
        scope_kind = "project"
        scope_label = project_name
    else:
        scope_kind = "task"
        scope_label = task_name

    return {
        "project_id": payload.get("projectId"),
        "task_id": task_id,
        "task_name": task_name,
        "activity_id": activity_id,
        "activity_title": activity_title,
        "is_general": activity_id is None,
        "scope_kind": scope_kind,
        "scope_label": scope_label,
    }


def _actor_snapshot(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    actor = payload.get("actor")
    actor_name = _clean_text(data.get("actor_name"))
    actor_company_name = _clean_text(data.get("actor_company_name"))
    actor_role = _clean_text(data.get("actor_role"))
    actor_avatar_url = _clean_text(data.get("actor_avatar_url"))

    if isinstance(actor, dict):
        first_name = _clean_text(actor.get("firstName"))
        last_name = _clean_text(actor.get("lastName"))
        derived_name = " ".join(chunk for chunk in [first_name, last_name] if chunk).strip()
        if not actor_name:
            actor_name = derived_name or _clean_text(actor.get("email")) or "Operatore"
        if not actor_company_name:
            actor_company_name = _clean_text(actor.get("companyName"))

    return {
        "profile_id": payload.get("profileId"),
        "name": actor_name or "Operatore",
        "company_name": actor_company_name or None,
        "role": actor_role or None,
        "avatar_url": actor_avatar_url or None,
    }


def _base_timeline_event(
    payload: dict[str, Any],
    *,
    event_kind: str,
    label: str,
    description: str,
    details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    timestamp = _clean_text(payload.get("timestamp")) or timezone.now().isoformat()
    occurred_at = timestamp
    occurred_at_ms = int(datetime.fromisoformat(occurred_at.replace("Z", "+00:00")).timestamp() * 1000)

    timeline_event = {
        "id": f"audit:{_clean_text(payload.get('eventId')) or _clean_text(payload.get('type'))}:{occurred_at}",
        "event_kind": event_kind,
        "occurred_at": occurred_at,
        "occurred_at_ms": occurred_at_ms,
        "label": label,
        "description": description,
        "searchable_text": _build_searchable_text(
            [
                label,
                description,
                data.get("project_name"),
                data.get("task_name"),
                data.get("activity_title"),
                data.get("member_name"),
                data.get("invite_email"),
                data.get("document_title"),
                data.get("folder_name"),
            ]
        ),
        "actor": _actor_snapshot(payload, data),
        "scope": _timeline_scope(payload, data),
        "target_post_id": payload.get("postId"),
        "target_comment_id": payload.get("commentId"),
        "target_folder_id": payload.get("folderId"),
        "target_document_id": payload.get("documentId"),
        "target_photo_id": payload.get("photoId"),
        "post_kind": data.get("post_kind"),
        "weather_snapshot": data.get("weather_snapshot"),
        "is_deleted": bool(data.get("is_deleted")),
        "is_alert": data.get("alert"),
        "details": details or [],
        "source": "audit",
        "category": _clean_text(data.get("category")) or _clean_text(payload.get("type")).split(".")[0],
    }
    timeline_event["searchable_text"] = _build_searchable_text(
        [
            timeline_event["searchable_text"],
            timeline_event["actor"].get("name"),
            timeline_event["actor"].get("company_name"),
            *[detail.get("label") for detail in timeline_event["details"]],
            *[detail.get("value") for detail in timeline_event["details"]],
        ]
    )
    return timeline_event


def build_timeline_event_from_realtime_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    event_type = _clean_text(payload.get("type"))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    task_name = _clean_text(data.get("task_name")) or "Fase operativa"
    activity_title = _clean_text(data.get("activity_title")) or "Lavorazione"
    member_name = _clean_text(data.get("member_name")) or "Collaboratore"
    document_title = _clean_text(data.get("document_title")) or "Documento"
    folder_name = _clean_text(data.get("folder_name")) or "Cartella"
    invite_email = _clean_text(data.get("invite_email")) or "Invito"
    excerpt = _clean_text(data.get("excerpt"))

    if event_type == "task.created":
        details = [
            _detail("Azienda", data.get("assigned_company_name")),
            _detail("Periodo", f"{_clean_text(data.get('date_start'))} -> {_clean_text(data.get('date_end'))}"),
            _detail("Progresso iniziale", f"{data.get('progress')}%", tone="positive"),
            _detail("Alert", "Attivo", tone="warning") if data.get("alert") else None,
            _detail("Nota", data.get("note")),
        ]
        return _base_timeline_event(
            payload,
            event_kind="task_created",
            label="Fase creata",
            description=f'Creata la fase "{task_name}".',
            details=[detail for detail in details if detail],
        )

    if event_type == "task.updated":
        completed = bool(data.get("completed"))
        details = _change_details(data.get("changes"))
        if not details:
            details = [
                _detail("Progresso", f"{data.get('progress')}%"),
                _detail("Alert", _bool_label(data.get("alert"))),
            ]
        return _base_timeline_event(
            payload,
            event_kind="task_completed" if completed else "task_updated",
            label="Fase completata" if completed else "Fase aggiornata",
            description=(
                f'La fase "{task_name}" risulta completata.'
                if completed
                else f'Aggiornata la fase "{task_name}".'
            ),
            details=[detail for detail in details if detail],
        )

    if event_type == "activity.created":
        details = [
            _detail("Task", data.get("task_name")),
            _detail("Stato", _status_label(data.get("status"))),
            _detail("Finestra", f"{_clean_text(data.get('datetime_start'))} -> {_clean_text(data.get('datetime_end'))}"),
            _detail("Squadra", ", ".join(data.get("worker_names") or [])),
            _detail("Alert", "Attivo", tone="warning") if data.get("alert") else None,
            _detail("Nota", data.get("note")),
        ]
        return _base_timeline_event(
            payload,
            event_kind="activity_created",
            label="Lavorazione creata",
            description=f'Creata la lavorazione "{activity_title}".',
            details=[detail for detail in details if detail],
        )

    if event_type == "activity.updated":
        completed = bool(data.get("completed"))
        return _base_timeline_event(
            payload,
            event_kind="activity_completed" if completed else "activity_updated",
            label="Lavorazione completata" if completed else "Lavorazione aggiornata",
            description=(
                f'La lavorazione "{activity_title}" risulta completata.'
                if completed
                else f'Aggiornata la lavorazione "{activity_title}".'
            ),
            details=_change_details(data.get("changes")),
        )

    if event_type == "post.created":
        post_kind = _clean_text(data.get("post_kind")).lower()
        if post_kind == "issue":
            event_kind = "issue_opened"
            label = "Segnalazione aperta"
        elif post_kind == "documentation":
            event_kind = "documentation_logged"
            label = "Documentazione registrata"
        else:
            event_kind = "work_logged"
            label = "Avanzamento registrato"
        details = [
            _detail("Tipo", _post_kind_label(data.get("post_kind"))),
            _detail("Visibilita", "Pubblico" if data.get("is_public") else "Privato"),
            _detail("Allegati", f"{int(data.get('attachment_count') or 0)} file"),
            _detail("Menzioni", str(int(data.get("mentioned_count") or 0))) if data.get("mentioned_count") else None,
        ]
        return _base_timeline_event(
            payload,
            event_kind=event_kind,
            label=label,
            description=_excerpt(excerpt, fallback=label),
            details=[detail for detail in details if detail],
        )

    if event_type in {"post.updated", "post.resolved"}:
        resolved = event_type == "post.resolved"
        details = _change_details(data.get("changes"))
        if not details:
            details = [
                _detail("Tipo", _post_kind_label(data.get("post_kind"))),
                _detail("Visibilita", "Pubblico" if data.get("is_public") else "Privato"),
                _detail("Allegati", f"{int(data.get('attachment_count') or 0)} file"),
            ]
        return _base_timeline_event(
            payload,
            event_kind="issue_resolved" if resolved else "post_updated",
            label="Segnalazione risolta" if resolved else "Post aggiornato",
            description=_excerpt(excerpt, fallback="Aggiornamento del contenuto operativo."),
            details=details,
        )

    if event_type == "post.deleted":
        return _base_timeline_event(
            payload,
            event_kind="post_deleted",
            label="Post eliminato",
            description="Il contenuto del post e stato rimosso dalla cronologia operativa.",
            details=[
                detail
                for detail in [
                    _detail("Tipo", _post_kind_label(data.get("post_kind"))),
                    _detail("Visibilita", "Pubblico" if data.get("is_public") else "Privato"),
                ]
                if detail
            ],
        )

    if event_type == "comment.created":
        return _base_timeline_event(
            payload,
            event_kind="comment_added",
            label="Commento aggiunto",
            description=_excerpt(excerpt, fallback="Nuovo commento registrato nel thread."),
            details=[
                detail
                for detail in [
                    _detail("Risposta a", f"Commento #{data.get('parent_id')}") if data.get("parent_id") else None,
                    _detail("Allegati", f"{int(data.get('attachment_count') or 0)} file") if data.get("attachment_count") else None,
                ]
                if detail
            ],
        )

    if event_type == "comment.updated":
        return _base_timeline_event(
            payload,
            event_kind="comment_updated",
            label="Commento aggiornato",
            description=_excerpt(excerpt, fallback="Commento aggiornato."),
            details=_change_details(data.get("changes")),
        )

    if event_type == "comment.deleted":
        return _base_timeline_event(
            payload,
            event_kind="comment_deleted",
            label="Commento eliminato",
            description="Il commento e stato rimosso dal thread operativo.",
            details=[
                detail
                for detail in [
                    _detail("Risposta a", f"Commento #{data.get('parent_id')}") if data.get("parent_id") else None,
                ]
                if detail
            ],
        )

    if event_type == "folder.created":
        return _base_timeline_event(
            payload,
            event_kind="folder_created",
            label="Cartella creata",
            description=f'Creata la cartella "{folder_name}".',
            details=[
                detail
                for detail in [
                    _detail("Percorso", data.get("path")),
                    _detail("Visibilita", "Pubblica" if data.get("is_public") else "Privata"),
                ]
                if detail
            ],
        )

    if event_type == "folder.updated":
        return _base_timeline_event(
            payload,
            event_kind="folder_updated",
            label="Cartella aggiornata",
            description=f'Aggiornata la cartella "{folder_name}".',
            details=_change_details(data.get("changes")),
        )

    if event_type == "folder.deleted":
        return _base_timeline_event(
            payload,
            event_kind="folder_deleted",
            label="Cartella eliminata",
            description=f'Rimossa la cartella "{folder_name}".',
            details=[
                detail
                for detail in [
                    _detail("Percorso", data.get("path")),
                ]
                if detail
            ],
        )

    if event_type == "document.created":
        return _base_timeline_event(
            payload,
            event_kind="document_created",
            label="Documento caricato",
            description=f'Caricato il documento "{document_title}".',
            details=[
                detail
                for detail in [
                    _detail("Cartella", data.get("folder_path")),
                    _detail("Dimensione", data.get("size_label")),
                    _detail("Visibilita", "Pubblico" if data.get("is_public") else "Privato"),
                ]
                if detail
            ],
        )

    if event_type == "document.updated":
        return _base_timeline_event(
            payload,
            event_kind="document_updated",
            label="Documento aggiornato",
            description=f'Aggiornato il documento "{document_title}".',
            details=_change_details(data.get("changes")),
        )

    if event_type == "document.deleted":
        return _base_timeline_event(
            payload,
            event_kind="document_deleted",
            label="Documento eliminato",
            description=f'Rimosso il documento "{document_title}".',
            details=[
                detail
                for detail in [
                    _detail("Cartella", data.get("folder_path")),
                ]
                if detail
            ],
        )

    if event_type == "team.member.added":
        return _base_timeline_event(
            payload,
            event_kind="team_member_added",
            label="Membro aggiunto",
            description=f"{member_name} e stato aggiunto al progetto.",
            details=[
                detail
                for detail in [
                    _detail("Ruolo", data.get("member_role")),
                    _detail("Azienda", data.get("member_company_name")),
                ]
                if detail
            ],
        )

    if event_type == "invite.created":
        return _base_timeline_event(
            payload,
            event_kind="invite_created",
            label="Invito generato",
            description=f"Creato un invito per {invite_email}.",
            details=[
                detail
                for detail in [
                    _detail("Scadenza", data.get("expires_at")),
                ]
                if detail
            ],
        )

    return None


def persist_project_operational_event(*, project_id: int, payload: dict[str, Any]) -> None:
    safe_payload = _json_safe(payload)
    timeline_event = build_timeline_event_from_realtime_payload(safe_payload)
    if timeline_event is not None:
        safe_payload["timeline"] = timeline_event

    occurred_at = _clean_text(safe_payload.get("timestamp"))
    parsed_occurred_at = timezone.now()
    if occurred_at:
        try:
            parsed_occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            if timezone.is_naive(parsed_occurred_at):
                parsed_occurred_at = timezone.make_aware(parsed_occurred_at, timezone.get_current_timezone())
        except ValueError:
            parsed_occurred_at = timezone.now()

    ProjectOperationalEvent.objects.create(
        project_id=project_id,
        event_type=_clean_text(safe_payload.get("type")) or "project.event",
        occurred_at=parsed_occurred_at,
        task_id_snapshot=safe_payload.get("taskId"),
        activity_id_snapshot=safe_payload.get("activityId"),
        post_id_snapshot=safe_payload.get("postId"),
        comment_id_snapshot=safe_payload.get("commentId"),
        folder_id_snapshot=safe_payload.get("folderId"),
        document_id_snapshot=safe_payload.get("documentId"),
        photo_id_snapshot=safe_payload.get("photoId"),
        member_id_snapshot=safe_payload.get("memberId"),
        invite_id_snapshot=safe_payload.get("inviteId"),
        actor_profile_id_snapshot=safe_payload.get("profileId"),
        payload=safe_payload,
    )


def list_project_operational_timeline(
    *,
    project_id: int,
    mode: str,
    task_id: int | None = None,
    activity_id: int | None = None,
) -> dict[str, Any]:
    queryset = ProjectOperationalEvent.objects.filter(project_id=project_id)

    if mode == "activity" and activity_id is not None:
        queryset = queryset.filter(activity_id_snapshot=activity_id)
    elif task_id is not None:
        scope_filter = Q(task_id_snapshot=task_id)
        if mode == "phase":
            scope_filter |= Q(task_id_snapshot__isnull=True, activity_id_snapshot__isnull=True)
        queryset = queryset.filter(scope_filter)

    events: list[dict[str, Any]] = []
    for item in queryset.order_by("-occurred_at", "-id"):
        timeline_event = item.payload.get("timeline") if isinstance(item.payload, dict) else None
        if not isinstance(timeline_event, dict):
            continue
        events.append(_json_safe(timeline_event))

    return {
        "mode": mode,
        "project_id": project_id,
        "task_id": task_id,
        "activity_id": activity_id,
        "events": events,
    }
