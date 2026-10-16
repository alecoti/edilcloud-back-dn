"""Declared, time-scoped professional roles never grant application permissions."""

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from ninja.errors import HttpError

from .models import Project, ProjectMemberStatus
from .provenance_models import Company, Person, ProjectParticipation


def role_labels(codes):
    from .services import PROJECT_ASSIGNMENT_ROLE_LABELS

    return [PROJECT_ASSIGNMENT_ROLE_LABELS.get(code, code) for code in codes]


def serialize_participation(row):
    return {
        "id": str(row.pk),
        "person_id": str(row.person_id),
        "company_id": str(row.company_id),
        "profile_id": row.person.profile_id,
        "person_name": row.person_name,
        "company_name": row.company_name,
        "qualification": row.qualification,
        "function": row.function,
        "role_codes": row.role_codes,
        "role_labels": role_labels(row.role_codes),
        "valid_from": row.valid_from.isoformat(),
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "status": row.status,
        "appointment_reference": row.appointment_reference,
        "origin": row.origin,
        "external": row.person.profile_id is None,
    }


def context(profile, project_id, *, edit=False):
    from .services import get_project_for_profile, get_project_membership, can_manage_project

    try:
        project = get_project_for_profile(profile=profile, project_id=project_id)
    except ValueError as exc:
        raise HttpError(404, "Cantiere non disponibile.") from exc
    member = get_project_membership(project, profile)
    if edit and not can_manage_project(member):
        raise HttpError(403, "Solo gli amministratori possono gestire anagrafica e incarichi.")
    return project, can_manage_project(member)


def list_participations(*, profile, project_id):
    from .services import PROJECT_ASSIGNMENT_ROLE_LABELS

    project, can_manage = context(profile, project_id)
    members = project.members.filter(
        status=ProjectMemberStatus.ACTIVE, disabled=False
    ).select_related("profile__workspace", "profile__user")
    members = list(members)
    observed = set(
        project.participations.filter(origin="membership").values_list(
            "person__profile_id", flat=True
        )
    )
    for member in members:
        if member.profile_id not in observed:
            sync_member(member, reconstructed=True)
    rows = project.participations.select_related("person").order_by("person_name", "-valid_from")
    return {
        "profile_id": profile.pk,
        "can_manage": can_manage,
        "role_labels": PROJECT_ASSIGNMENT_ROLE_LABELS,
        "participants": [serialize_participation(row) for row in rows],
        "members": [
            {
                "profile_id": m.profile_id,
                "name": m.profile.member_name,
                "company_name": m.profile.workspace.name,
            }
            for m in members
        ],
    }


def parse_at(value, *, default=None):
    if value in (None, ""):
        return default
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "Data dell'incarico non valida.") from exc


@transaction.atomic
def create_participation(*, profile, project_id, payload):
    from .services import PROJECT_ASSIGNMENT_ROLE_LABELS

    project, _ = context(profile, project_id, edit=True)
    Project.objects.select_for_update().get(pk=project.pk)
    name = payload.person_name.strip()
    company_name = payload.company_name.strip()
    if not name or not company_name:
        raise HttpError(400, "Indica persona e azienda.")
    codes = list(dict.fromkeys(payload.role_codes))
    if set(codes) - set(PROJECT_ASSIGNMENT_ROLE_LABELS):
        raise HttpError(400, "Incarico di progetto non valido.")
    start = parse_at(payload.valid_from, default=timezone.now())
    end = parse_at(payload.valid_to)
    if end and end <= start:
        raise HttpError(400, "La fine dell'incarico deve essere successiva all'inizio.")
    linked_profile = None
    if payload.profile_id:
        member = (
            project.members.filter(
                profile_id=payload.profile_id, status=ProjectMemberStatus.ACTIVE, disabled=False
            )
            .select_related("profile")
            .first()
        )
        if not member:
            raise HttpError(400, "Il profilo non è un partecipante attivo di questo cantiere.")
        linked_profile = member.profile
    if payload.person_id:
        person = Person.objects.filter(
            pk=payload.person_id, workspace_id=project.workspace_id
        ).first()
        if not person:
            raise HttpError(404, "Persona non disponibile in questa anagrafica.")
        if linked_profile and person.profile_id != linked_profile.pk:
            raise HttpError(400, "La persona e il profilo indicati non corrispondono.")
    elif linked_profile:
        person, _ = Person.objects.get_or_create(
            workspace_id=project.workspace_id, profile=linked_profile, defaults={"name": name}
        )
    else:
        person = Person.objects.create(workspace_id=project.workspace_id, name=name)
    if payload.company_id:
        company = Company.objects.filter(
            pk=payload.company_id, workspace_id=project.workspace_id
        ).first()
        if not company:
            raise HttpError(404, "Azienda non disponibile in questa anagrafica.")
    else:
        company, _ = Company.objects.get_or_create(
            workspace_id=project.workspace_id,
            name=company_name,
            linked_workspace=None,
            defaults={"tax_id": payload.tax_id.strip()},
        )
    if payload.status not in {"declared", "verified"}:
        raise HttpError(400, "Stato dell'incarico non valido.")
    if payload.status == "verified" and not payload.appointment_reference.strip():
        raise HttpError(400, "Indica il riferimento verificato dell'incarico.")
    row = ProjectParticipation.objects.create(
        project=project,
        person=person,
        company=company,
        person_name=name,
        company_name=company_name,
        qualification=payload.qualification.strip(),
        function=payload.function.strip(),
        role_codes=codes,
        valid_from=start,
        valid_to=end,
        status=payload.status,
        recorded_by=profile,
        appointment_reference=payload.appointment_reference.strip(),
    )
    return serialize_participation(row)


@transaction.atomic
def close_participation(*, profile, project_id, participation_id, valid_to):
    project, _ = context(profile, project_id, edit=True)
    row = (
        project.participations.select_for_update()
        .select_related("person")
        .filter(pk=participation_id)
        .first()
    )
    if not row:
        raise HttpError(404, "Incarico non disponibile.")
    end = parse_at(valid_to, default=timezone.now())
    if end <= row.valid_from or (row.valid_to and end != row.valid_to):
        raise HttpError(409, "Un incarico già chiuso non può essere riscritto.")
    row.valid_to = end
    row.save(update_fields=["valid_to", "updated_at"])
    return serialize_participation(row)


@transaction.atomic
def sync_member(member, *, reconstructed=False):
    """Capture changes from the existing Team API; never manufacture a nomina."""
    project = member.project
    Project.objects.select_for_update().get(pk=project.pk)
    profile = member.profile
    person, _ = Person.objects.get_or_create(
        workspace_id=project.workspace_id, profile=profile, defaults={"name": profile.member_name}
    )
    company, _ = Company.objects.get_or_create(
        workspace_id=project.workspace_id,
        linked_workspace_id=profile.workspace_id,
        defaults={"name": profile.workspace.name},
    )
    current = project.participations.filter(
        person=person, origin="membership", valid_to__isnull=True
    ).first()
    values = {
        "person_name": profile.member_name,
        "company_name": profile.workspace.name,
        "qualification": profile.position,
        "role_codes": member.project_role_codes,
    }
    active = member.status == ProjectMemberStatus.ACTIVE and not member.disabled
    if current and active and all(getattr(current, key) == value for key, value in values.items()):
        return current
    now = timezone.now()
    if current:
        current.valid_to = max(now, current.valid_from + timedelta(microseconds=1))
        current.save(update_fields=["valid_to", "updated_at"])
    if not active:
        return None
    # A backfill observes the membership now; its creation time does not prove
    # the same qualification/company held throughout the earlier interval.
    return ProjectParticipation.objects.create(
        project=project,
        person=person,
        company=company,
        **values,
        valid_from=now,
        origin="membership",
        status="reconstructed" if reconstructed else "captured",
    )


def actor_snapshot(*, project, profile, at, reconstructed=False):
    if profile is None:
        return {
            "person_name": "",
            "company_name": "",
            "qualification": "",
            "roles": [],
            "identity_state": "unavailable",
            "captured_at": timezone.now().isoformat(),
        }
    records = (
        project.participations.filter(person__profile=profile, valid_from__lte=at)
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=at))
        .select_related("person", "company")
    )
    records = list(records)
    # Do not insert current roles into a past interval when no history exists.
    known = not reconstructed
    roles = list(dict.fromkeys(code for row in records for code in row.role_codes))
    return {
        "person_name": records[0].person_name if records else profile.member_name,
        "person_uuid": str(records[0].person_id) if records else None,
        "profile_id": profile.pk,
        "company_name": " / ".join(dict.fromkeys(r.company_name for r in records))
        or profile.workspace.name,
        "company_uuids": list(dict.fromkeys(str(r.company_id) for r in records)),
        "qualification": " / ".join(
            dict.fromkeys(r.qualification for r in records if r.qualification)
        )
        or profile.position,
        "roles": roles,
        "role_labels": role_labels(roles),
        "participations": [serialize_participation(row) for row in records],
        "identity_state": "captured" if known else "reconstructed",
        "historical_roles_known": bool(records)
        and all(r.status != "reconstructed" for r in records),
        "identity_at": at.isoformat(),
        "captured_at": timezone.now().isoformat(),
    }
