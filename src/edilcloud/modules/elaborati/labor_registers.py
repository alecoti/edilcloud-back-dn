"""Private labor ledger: append-only revisions and recoverable commands."""
from copy import deepcopy
import json
from datetime import date, datetime, timedelta
from uuid import UUID
from django.db import connection, transaction
from django.db.models import F, Q
from django.utils import timezone
from ninja.errors import HttpError
from edilcloud.modules.projects.services import get_project_for_profile, get_project_membership
from edilcloud.modules.workspaces.models import Profile
from .content import digest
from .labor_models import LaborIdentity, LaborLine, LaborOperation, LaborRegister, LaborRevision
from .labor_proposals import labor_proposal

MANAGERS = {"o", "d", "m"}


def identifier(value, field):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower():
            raise ValueError()
        return UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HttpError(400, f"{field}: UUID non valido.") from exc


def actor(profile, *, lock=False):
    query = Profile.objects.select_related("workspace", "user").filter(
        pk=profile.pk, is_active=True, workspace__is_active=True, user__is_active=True
    )
    if lock:
        query = query.select_for_update(of=("self",))
    current = query.first()
    if current is None:
        raise HttpError(403, "Profilo aziendale non disponibile.")
    return current


def project_access(profile, project_id, *, lock=False):
    if type(project_id) is not int or not 0 < project_id <= 2**63 - 1:
        raise HttpError(400, "project_id: identificativo non valido.")
    try:
        project = get_project_for_profile(profile=profile, project_id=project_id)
        get_project_membership(project, profile)
        if lock:
            from edilcloud.modules.projects.models import ProjectMember
            if not ProjectMember.objects.select_for_update().filter(project=project, profile=profile, status=1, disabled=False).exists():
                raise ValueError("Membership changed")
        return project
    except ValueError as exc:
        raise HttpError(404, "Progetto non trovato o non accessibile.") from exc


def snapshot(profile):
    return {"profile_id": profile.pk, "workspace_id": profile.workspace_id,
            "name": profile.member_name, "role": profile.role}


def authorized_register(profile, register_id, *, lock=False):
    query = LaborRegister.objects.filter(pk=register_id, workspace_id=profile.workspace_id)
    if profile.role not in MANAGERS:
        query = query.filter(created_by_id=profile.pk)
    if lock:
        query = query.select_for_update()
    register = query.first()
    if register is None:
        raise HttpError(404, "Registro non trovato o non accessibile.")
    project_access(profile, register.project_id, lock=lock)
    return register


def identity_view(identity):
    return {"id": str(identity.pk), "key": str(identity.pk), "kind": identity.kind,
            "name": identity.name, "external_reference": identity.external_reference,
            "profile_id": identity.profile_id, "basis": identity.basis, "active": identity.active}


def view(register, revision=None, history=None):
    revision = revision or register.revisions.get(number=register.current_version)
    if history is None:
        history = list(register.revisions.order_by("-number").values(
            "number", "state", "action", "reason", "review_mode", "content_hash", "created_at"))
    for item in history:
        if not isinstance(item["created_at"], str):
            item["created_at"] = item["created_at"].isoformat(timespec="microseconds")
    return {"schema": "labor-register-v1", "id": str(register.pk), "project_id": register.project_id,
            "workspace_id": register.workspace_id, "visibility": "private",
            "created_by_id": register.created_by_id, "version": revision.number,
            "head_version": register.current_version, "effective_version": register.effective_version,
            "revision_id": str(revision.pk), "state": revision.state, "work_date": str(revision.work_date),
            "timezone": revision.timezone, "content_hash": revision.content_hash, "data": revision.data,
            "actor": revision.actor_snapshot, "action": revision.action, "reason": revision.reason,
            "review_mode": revision.review_mode, "replaces_version": revision.replaces_version,
            "created_at": revision.created_at.isoformat(timespec="microseconds"), "history": history}


def operation_result(profile, operation, *, replayed):
    result = {"operation_id": str(operation.command_id), "replayed": replayed}
    if operation.identity_id:
        if operation.identity.workspace_id != profile.workspace_id:
            raise HttpError(404, "Operazione non trovata.")
        result["identity"] = identity_view(operation.identity)
    else:
        register = authorized_register(profile, operation.register_id)
        result["register"] = view(register, operation.revision)
    return result


def previous(profile, command_id, request_hash=None):
    found = LaborOperation.objects.select_related("identity", "revision").filter(
        workspace_id=profile.workspace_id, actor_key=profile.pk, command_id=command_id
    ).first()
    if found and request_hash is not None and found.request_hash != request_hash:
        raise HttpError(409, "La chiave di invio è già associata a un'altra operazione.")
    return operation_result(profile, found, replayed=True) if found else None


def recover(profile, command_id):
    profile = actor(profile)
    result = previous(profile, command_id)
    if result is None:
        raise HttpError(404, "Operazione non trovata.")
    return result


def identities(profile, project_id, q=""):
    profile = actor(profile)
    project_access(profile, project_id)
    query = LaborIdentity.objects.filter(workspace_id=profile.workspace_id, active=True)
    people = Profile.objects.filter(workspace_id=profile.workspace_id, is_active=True, user__is_active=True)
    if q:
        query = query.filter(name__icontains=q[:200])
        people = people.filter(Q(first_name__icontains=q[:200]) | Q(last_name__icontains=q[:200]))
    return {"items": [identity_view(i) for i in query.order_by("name", "id")[:100]],
            "profile_candidates": [{"profile_id": p.pk, "name": p.member_name} for p in people.order_by("first_name", "last_name", "pk")[:100]],
            "can_manage": profile.role in MANAGERS, "current_profile_id": profile.pk, "current_role": profile.role}


@transaction.atomic
def create_identity(profile, body):
    profile = actor(profile, lock=True)
    project_access(profile, body.get("project_id"), lock=True)
    key = identifier(body.get("command_id"), "command_id")
    request_hash = digest({"action": "identity.create", "body": body})
    replay = previous(profile, key, request_hash)
    if replay:
        return replay
    kind = body.get("kind")
    linked = body.get("profile_id")
    if kind not in ("person", "team"):
        raise HttpError(400, "Tipo di identità non valido.")
    if profile.role not in MANAGERS and (kind != "person" or type(linked) is not int or linked != profile.pk):
        raise HttpError(403, "L'anagrafica aziendale richiede un responsabile.")
    person = None
    if linked is not None:
        if kind != "person" or type(linked) is not int:
            raise HttpError(400, "Il collegamento al profilo richiede una persona.")
        person = Profile.objects.filter(pk=linked, workspace_id=profile.workspace_id, is_active=True, user__is_active=True).first()
        if person is None:
            raise HttpError(404, "Profilo aziendale non disponibile.")
    name = person.member_name if person else body.get("name")
    reference = body.get("external_reference", "")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200 or not isinstance(reference, str) or len(reference) > 100:
        raise HttpError(400, "Nome o riferimento dell'identità non valido.")
    existing = LaborIdentity.objects.filter(workspace_id=profile.workspace_id, profile=person).first() if person else None
    if existing:
        if not existing.active:
            raise HttpError(409, "L'identità aziendale risulta disattivata.")
        identity = existing
    else:
        fields = dict(kind=kind, name=name.strip(), external_reference=reference.strip(),
            basis="profile" if person else "declared", created_by=profile)
        if person:
            identity, _ = LaborIdentity.objects.get_or_create(workspace=profile.workspace, profile=person, defaults=fields)
            if not identity.active:
                raise HttpError(409, "L'identità aziendale risulta disattivata.")
        else:
            identity = LaborIdentity.objects.create(workspace=profile.workspace, **fields)
    operation = LaborOperation.objects.create(workspace=profile.workspace, actor_key=profile.pk,
        command_id=key, request_hash=request_hash, identity=identity)
    return operation_result(profile, operation, replayed=False)


def prepare(profile, payload):
    try:
        labor_proposal(payload)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    cleaned, supplied = deepcopy(payload), {}
    ids = []
    for row in payload["rows"]:
        try:
            ids.append(UUID(row["subject"].get("key", "")))
        except (ValueError, TypeError, AttributeError):
            pass
    catalog = {str(item.pk): item for item in LaborIdentity.objects.select_related("profile__user").filter(
        pk__in=ids, workspace_id=profile.workspace_id, active=True)}
    for row in cleaned["rows"]:
        raw_key = row["subject"].get("key")
        item = catalog.get(raw_key.lower()) if isinstance(raw_key, str) else None
        if item and item.kind == row["subject"]["kind"] and (
            item.basis != "profile" or item.profile_id and item.profile.is_active and item.profile.user.is_active
            and item.profile.workspace_id == profile.workspace_id
        ):
            row["subject"]["key"], row["subject"]["name"] = str(item.pk), item.name
            supplied[str(item.pk)] = identity_view(item)
    proposal = labor_proposal(cleaned)
    for row in proposal["rows"]:
        if row["subject"]["key"] in supplied:
            row["identity_status"] = "resolved"
        else:
            if not any(i["code"] == "identity_required" for i in row["issues"]):
                row["issues"].append({"field": "subject.key", "code": "identity_unavailable",
                    "message": "Seleziona un'identità aziendale attiva e coerente con la riga."})
            row["calculation_status"] = "needs_clarification"
    proposal["requires_identity_validation"] = any(r["identity_status"] != "resolved" for r in proposal["rows"])
    proposal["totals"]["unresolved_rows"] = sum(bool(r["issues"]) for r in proposal["rows"])
    proposal["totals"]["resolved_person_minutes"] = sum(r["person_minutes"] or 0 for r in proposal["rows"] if not r["issues"])
    return {"input": deepcopy(payload), "proposal": proposal, "identities": supplied,
            "prepared_by": snapshot(profile)}


def validate_resources(profile, register, data):
    proposal = data["proposal"]
    if proposal["totals"]["unresolved_rows"] or proposal["requires_identity_validation"]:
        raise HttpError(400, "Risolvi i punti da chiarire prima di confermare le ore.")
    ids = sorted(UUID(key) for key in data["identities"])
    current = list(LaborIdentity.objects.select_for_update(of=("self",)).select_related("profile__user").filter(
        pk__in=ids, workspace_id=profile.workspace_id, active=True).order_by("id"))
    if len(current) != len(ids) or any(i.basis == "profile" and (
        i.profile_id is None or not i.profile.is_active or not i.profile.user.is_active
        or i.profile.workspace_id != profile.workspace_id) for i in current):
        raise HttpError(409, "Un'identità aziendale è cambiata. Rivedi le righe prima di confermare.")
    day = date.fromisoformat(proposal["work_date"])
    sql = """SELECT jsonb_build_object('identity_id',l.identity_id::text,'work_date',l.work_date::text,
    'register_id',g.id::text,'revision_number',r.number,
    'person_minutes',l.person_minutes,'started_at',l.started_at,'ended_at',l.ended_at,'break_minutes',l.break_minutes)
    FROM elaborati_laborline l JOIN elaborati_laborrevision r ON r.id=l.revision_id
    JOIN elaborati_laborregister g ON g.id=r.register_id
    JOIN elaborati_laborrevision h ON h.register_id=g.id AND h.number=g.current_version
    WHERE g.workspace_id=%s AND g.id<>%s AND l.identity_id=ANY(%s::uuid[])
    AND l.work_date BETWEEN %s AND %s
    AND (r.number=g.effective_version OR (r.number=g.current_version AND h.state IN ('confirmed','submitted')))"""
    with connection.cursor() as cursor:
        cursor.execute(sql, [profile.workspace_id, register.pk, ids, day-timedelta(days=1), day+timedelta(days=1)])
        others = [json.loads(r[0]) if isinstance(r[0], str) else r[0] for r in cursor.fetchall()]
    warnings = set()
    for row in proposal["rows"]:
        kind = row["subject"]["kind"]
        if kind == "team":
            warnings.add("team_coverage_unverified")
        relevant = [o for o in others if o["identity_id"] == row["subject"]["key"]]
        per_revision = {}
        for other in relevant:
            if other["work_date"] == str(day):
                version = (other["register_id"], other["revision_number"])
                per_revision[version] = per_revision.get(version, 0) + other["person_minutes"]
        per_register = {}
        for (register_id, _), amount in per_revision.items():
            per_register[register_id] = max(per_register.get(register_id, 0), amount)
        if kind == "person" and row["person_minutes"] + sum(per_register.values()) > 1500:
            raise HttpError(409, "Il totale della persona supera il tempo disponibile nel giorno operativo.")
        interval = row["time"]["mode"] == "interval"
        for other in relevant:
            if not interval or not other["started_at"]:
                if other["work_date"] == str(day):
                    warnings.add("overlap_without_exact_times")
                continue
            start, end = datetime.fromisoformat(row["time"]["start"].replace("Z", "+00:00")), datetime.fromisoformat(row["time"]["end"].replace("Z", "+00:00"))
            first, last = datetime.fromisoformat(other["started_at"]), datetime.fromisoformat(other["ended_at"])
            overlap = max(0, int((min(end, last)-max(start, first)).total_seconds()//60))
            if overlap > row["time"]["break_minutes"] + (other["break_minutes"] or 0):
                raise HttpError(409, "Sovrapposizione con un'altra registrazione aziendale della stessa identità.")
            if overlap:
                warnings.add("overlap_break_position_unknown")
    return {"scope": "registered_company_data", "warnings": sorted(warnings),
            "presence_verified": False, "cross_company_checked": False}


def write_revision(register, profile, data, state, action, *, reason="", review_mode="", initial=False):
    number = 1 if initial else register.current_version + 1
    revision = LaborRevision.objects.create(register=register, number=number, state=state,
        work_date=data["proposal"]["work_date"], timezone=data["proposal"]["timezone"],
        data=data, content_hash=digest(data), actor=profile, actor_snapshot=snapshot(profile),
        action=action, reason=reason, review_mode=review_mode, replaces_version=register.effective_version)
    lines = []
    for row in data["proposal"]["rows"]:
        key = row["subject"]["key"]
        if key not in data["identities"] or not row["minutes"] or not row["person_minutes"]:
            continue
        clock = row["time"]
        lines.append(LaborLine(revision=revision, identity_id=UUID(key), row_id=UUID(row["id"]),
            work_date=revision.work_date, minutes=row["minutes"], person_minutes=row["person_minutes"],
            started_at=datetime.fromisoformat(clock["start"].replace("Z", "+00:00")) if clock["mode"] == "interval" and clock["start"] else None,
            ended_at=datetime.fromisoformat(clock["end"].replace("Z", "+00:00")) if clock["mode"] == "interval" and clock["end"] else None,
            break_minutes=clock.get("break_minutes") if clock["mode"] == "interval" else None))
    LaborLine.objects.bulk_create(lines)
    if not initial:
        register.current_version = number
        if state == "approved":
            register.effective_version = number
        register.updated_at = timezone.now()
        register.save(update_fields=("current_version", "effective_version", "updated_at"))
    return revision


@transaction.atomic
def create_register(profile, body):
    profile = actor(profile, lock=True)
    key = identifier(body.get("command_id"), "command_id")
    payload = body.get("proposal")
    if not isinstance(payload, dict):
        raise HttpError(400, "proposal: oggetto richiesto.")
    project = project_access(profile, payload.get("project_id"), lock=True)
    request_hash = digest({"action": "register.create", "body": body})
    replay = previous(profile, key, request_hash)
    if replay:
        return replay
    data = prepare(profile, payload)
    register = LaborRegister.objects.create(workspace=profile.workspace, project=project, created_by=profile)
    revision = write_revision(register, profile, data, "draft", "create", initial=True)
    operation = LaborOperation.objects.create(workspace=profile.workspace, actor_key=profile.pk,
        command_id=key, request_hash=request_hash, register=register, revision=revision)
    return operation_result(profile, operation, replayed=False)


@transaction.atomic
def command(profile, register_id, body):
    profile = actor(profile, lock=True)
    register = authorized_register(profile, register_id, lock=True)
    key = identifier(body.get("command_id"), "command_id")
    request_hash = digest({"action": "register.command", "register_id": str(register.pk), "body": body})
    replay = previous(profile, key, request_hash)
    if replay:
        return replay
    version = body.get("expected_version")
    if type(version) is not int or version != register.current_version:
        raise HttpError(409, "Il registro è cambiato. Confronta la versione corrente prima di inviare.")
    head = register.revisions.get(number=version)
    action = body.get("action")
    data, reason, review = deepcopy(head.data), body.get("reason", ""), ""
    if not isinstance(reason, str) or len(reason) > 1000:
        raise HttpError(400, "Motivazione non valida.")
    if action in ("save", "correct"):
        if action == "save" and head.state not in ("draft", "confirmed", "rejected"):
            raise HttpError(409, "Crea una rettifica esplicita prima di modificare questa versione.")
        if action == "correct" and len(reason.strip()) < 8:
            raise HttpError(400, "Indica una motivazione della rettifica di almeno otto caratteri.")
        payload = body.get("proposal")
        if not isinstance(payload, dict) or payload.get("project_id") != register.project_id:
            raise HttpError(400, "La proposta deve appartenere al cantiere del registro.")
        data, state = prepare(profile, payload), "draft"
    else:
        if body.get("content_hash") != head.content_hash:
            raise HttpError(409, "I valori da confermare sono cambiati. Rivedi la versione corrente.")
        if action == "confirm" and head.state == "draft":
            if body.get("confirmed") is not True:
                raise HttpError(400, "Conferma esplicitamente le ore della versione mostrata.")
            data["checks"] = validate_resources(profile, register, data)
            state = "confirmed"
        elif action == "submit" and head.state == "confirmed":
            state = "submitted"
        elif action in ("approve", "reject") and head.state in ("confirmed", "submitted"):
            if profile.role not in MANAGERS:
                raise HttpError(403, "La revisione delle ore richiede un responsabile aziendale.")
            if action == "reject":
                if len(reason.strip()) < 8:
                    raise HttpError(400, "Indica il motivo del rifiuto, almeno otto caratteri.")
                state = "rejected"
            else:
                if body.get("confirmed") is not True:
                    raise HttpError(400, "Conferma esplicitamente l'approvazione dei valori mostrati.")
                self_review = data["prepared_by"]["profile_id"] == profile.pk
                if self_review and (profile.role not in ("o", "d") or body.get("self_approval_acknowledged") is not True):
                    raise HttpError(403, "Serve un altro responsabile oppure la conferma esplicita del titolare/delegato per l'autoapprovazione.")
                checks = validate_resources(profile, register, data)
                if checks["warnings"] and body.get("overlap_acknowledged") is not True:
                    raise HttpError(409, "Verifica la copertura delle squadre o le possibili sovrapposizioni e conferma il controllo manuale.")
                data["checks"] = checks
                review, state = ("self" if self_review else "separate"), "approved"
        else:
            raise HttpError(409, "Azione non disponibile nello stato corrente del registro.")
    revision = write_revision(register, profile, data, state, action, reason=reason.strip(), review_mode=review)
    operation = LaborOperation.objects.create(workspace=profile.workspace, actor_key=profile.pk,
        command_id=key, request_hash=request_hash, register=register, revision=revision)
    return operation_result(profile, operation, replayed=False)


def read(profile, register_id, version=None):
    profile = actor(profile)
    register = authorized_register(profile, register_id)
    revision = None
    if version is not None:
        revision = register.revisions.filter(number=version).first()
        if revision is None:
            raise HttpError(404, "Versione del registro non trovata.")
    return view(register, revision)


def listing(profile, project_id, start=None, end=None, offset=0, limit=30):
    profile = actor(profile)
    project_access(profile, project_id)
    query = LaborRegister.objects.filter(workspace_id=profile.workspace_id, project_id=project_id)
    if profile.role not in MANAGERS:
        query = query.filter(created_by=profile)
    if start or end:
        revisions = LaborRevision.objects.filter(register__workspace_id=profile.workspace_id, number=F("register__current_version"))
        if start:
            revisions = revisions.filter(work_date__gte=start)
        if end:
            revisions = revisions.filter(work_date__lte=end)
        query = query.filter(id__in=revisions.values("register_id"))
    limit, offset = min(100, max(1, limit)), max(0, offset)
    selected = list(query.order_by("-updated_at", "-id")[offset:offset+limit])
    heads = {r.register_id: r for r in LaborRevision.objects.filter(register__in=selected, number=F("register__current_version"))}
    histories = {r.pk: [] for r in selected}
    for item in LaborRevision.objects.filter(register__in=selected).order_by("-number").values(
        "register_id", "number", "state", "action", "reason", "review_mode", "content_hash", "created_at"):
        register_id = item.pop("register_id")
        histories[register_id].append(item)
    return {"items": [view(item, heads[item.pk], histories[item.pk]) for item in selected],
            "total": query.count(), "offset": offset, "limit": limit}
