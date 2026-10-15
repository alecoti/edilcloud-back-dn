"""Project settings reuse the authorization rules enforced by existing operations."""
from datetime import date

from django.db import transaction
from ninja.errors import HttpError

from .models import Project, ProjectMember, ProjectMemberStatus
from .notification_preferences import DEFAULT_NOTIFICATION_PREFERENCES, resolved_notification_preferences
from edilcloud.modules.workspaces.models import WorkspaceRole
from edilcloud.modules.workspaces.services import get_role_priority

ROLE_LABELS = {"o": "Titolare", "d": "Amministratore cantiere", "m": "Responsabile operativo", "w": "Operativo"}


def _context(profile, project_id, lock=False):
    from .services import get_project_for_profile, get_project_membership
    if lock:
        Project.objects.select_for_update().filter(pk=project_id).first()
    project = get_project_for_profile(profile=profile, project_id=project_id)
    return project, get_project_membership(project, profile)


def _require_manage(member):
    from .services import can_manage_project
    if not can_manage_project(member):
        raise HttpError(403, "Solo gli amministratori del cantiere possono modificare questi dati.")


def permissions_for_member(member):
    from .services import can_manage_project, can_edit_project
    if member.disabled or member.status != ProjectMemberStatus.ACTIVE:
        return dict.fromkeys(("view", "publish", "edit_own", "edit_all", "manage_documents", "manage_schedule", "manage_members", "manage_project"), False)
    return {"view": True, "publish": True, "edit_own": True,
        "edit_all": can_edit_project(member), "manage_documents": can_edit_project(member),
        "manage_schedule": can_edit_project(member), "manage_members": can_manage_project(member),
        "manage_project": can_manage_project(member)}


def _member_settings(member):
    from .services import project_member_effective_role
    profile = member.profile
    minimum = profile.role if profile.workspace_id == member.project.workspace_id else WorkspaceRole.WORKER
    effective = project_member_effective_role(member)
    protected = member.profile_id == member.project.created_by_id or effective == WorkspaceRole.OWNER
    return {"id": member.id, "profile_id": profile.id,
        "name": profile.member_name, "company_name": profile.workspace.name,
        "role": effective, "role_label": ROLE_LABELS.get(effective, "Operativo"),
        "minimum_role": minimum, "protected": protected, "enabled": not member.disabled,
        "allowed_roles": [] if protected else [role for role in ("w", "m", "d") if get_role_priority(role) >= get_role_priority(minimum)],
        "permissions": permissions_for_member(member)}


def get_project_settings(*, profile, project_id):
    from .services import can_manage_project
    project, member = _context(profile, project_id)
    members = project.members.filter(status=ProjectMemberStatus.ACTIVE).select_related("project", "profile__workspace", "profile__user")
    if not can_manage_project(member):
        members = members.filter(disabled=False)
    return {"project": {"id": project.id, "name": project.name, "description": project.description,
        "address": project.address, "date_start": project.date_start.isoformat(),
        "date_end": project.date_end.isoformat() if project.date_end else None, "status": project.status,
        "is_demo": project.is_demo_master, "latitude": project.latitude, "longitude": project.longitude, "google_place_id": project.google_place_id},
        "profile_id": profile.id, "member_id": member.id, "can_manage": can_manage_project(member),
        "permissions": permissions_for_member(member),
        "notification_preferences": resolved_notification_preferences(member),
        "members": [_member_settings(item) for item in members.order_by("profile__first_name", "profile__last_name", "id")],
        "role_labels": ROLE_LABELS}


@transaction.atomic
def update_project_settings(*, profile, project_id, general=None, notification_preferences=None):
    from .services import emit_project_realtime_event
    project, member = _context(profile, project_id, lock=True)
    if general is not None:
        _require_manage(member)
        previous_address = project.address
        allowed = {"name", "description", "address", "date_start", "date_end"}
        if set(general) - allowed:
            raise ValueError("Impostazioni del cantiere non valide.")
        for key in ("name", "description", "address"):
            if key in general:
                value = general[key]
                if not isinstance(value, str) or len(value.strip()) > (10000 if key == "description" else 255):
                    raise ValueError("Testo delle impostazioni non valido.")
                setattr(project, key, value.strip())
        if not project.name:
            raise ValueError("Il nome del cantiere è obbligatorio.")
        for key in ("date_start", "date_end"):
            if key in general:
                value = general[key]
                if value is None and key == "date_start":
                    raise ValueError("La data di inizio è obbligatoria.")
                if value is not None and not isinstance(value, (str, date)):
                    raise ValueError("Data del cantiere non valida.")
                setattr(project, key, date.fromisoformat(value) if isinstance(value, str) else value)
        if project.date_end and project.date_end < project.date_start:
            raise ValueError("La fine del cantiere non può precedere l'inizio.")
        if "address" in general and project.address != previous_address:
            # Never keep the previous location's weather or map after an address edit.
            from edilcloud.platform.geocoding import geocode_address
            location = geocode_address(project.address) if project.address else None
            project.latitude = location.latitude if location else None
            project.longitude = location.longitude if location else None
            project.google_place_id = ""
        project.save()
        emit_project_realtime_event(event_type="project.settings.updated", project_id=project.id,
            actor_profile=profile, data={"changed_fields": sorted(general), "project_name": project.name})
    if notification_preferences is not None:
        if set(notification_preferences) - DEFAULT_NOTIFICATION_PREFERENCES.keys() or any(type(value) is not bool for value in notification_preferences.values()):
            raise ValueError("Preferenze notifiche non valide.")
        member.notification_preferences = {**resolved_notification_preferences(member), **notification_preferences}
        member.save(update_fields=["notification_preferences", "updated_at"])
    return get_project_settings(profile=profile, project_id=project_id)


@transaction.atomic
def update_project_member_settings(*, profile, project_id, member_id, role=None, enabled=None):
    from .services import emit_project_realtime_event
    project, actor = _context(profile, project_id, lock=True)
    _require_manage(actor)
    member = ProjectMember.objects.select_related("project", "profile__workspace", "profile__user").filter(
        project=project, id=member_id, status=ProjectMemberStatus.ACTIVE).first()
    if member is None:
        raise HttpError(404, "Membro del cantiere non trovato.")
    settings = _member_settings(member)
    if settings["protected"]:
        raise HttpError(403, "Il titolare del cantiere mantiene i permessi di amministrazione.")
    if member.id == actor.id:
        raise ValueError("Non puoi modificare i tuoi permessi o disattivare il tuo accesso.")
    if role is not None:
        if role not in settings["allowed_roles"]:
            raise ValueError("Ruolo non consentito: i permessi aziendali non possono essere ridotti dal cantiere.")
        member.role = role
    if enabled is not None:
        if type(enabled) is not bool:
            raise ValueError("Stato di accesso non valido.")
        member.disabled = not enabled
    member.save(update_fields=["role", "disabled", "updated_at"])
    emit_project_realtime_event(event_type="team.member.permissions.updated", project_id=project.id,
        actor_profile=profile, data={"member_id": member.id, "member_profile_id": member.profile_id,
            "enabled": not member.disabled, "role": member.role})
    return get_project_settings(profile=profile, project_id=project_id)
