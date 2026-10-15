import io
import math
import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from ninja.errors import HttpError
from PIL import Image, ImageDraw

from edilcloud.modules.projects.models import Project, ProjectMemberStatus
from edilcloud.modules.projects.services import (
    can_edit_project,
    get_project_for_profile,
    get_project_membership,
    profile_display_name,
    project_access_queryset,
)

from .content import digest, validate_editor
from .jobs import queue_job
from .models import (
    DocumentAudit,
    DocumentJob,
    Elaborato,
    ElaboratoRevision,
    PersonalSignature,
    WorkspaceDocumentStyle,
)
from .registry import template_for


def require_project_editor(profile, project):
    member = get_project_membership(project, profile)
    if not can_edit_project(member):
        raise HttpError(
            403, "La redazione e la pubblicazione richiedono il ruolo di responsabile del progetto."
        )


def authorize_revision(*, profile, revision, edit=False):
    try:
        project = get_project_for_profile(profile=profile, project_id=revision.elaborato.project_id)
    except ValueError as exc:
        raise HttpError(404, "Elaborato non trovato o non accessibile.") from exc
    if edit or revision.state == "draft":
        require_project_editor(profile, project)
    return project


def get_revision(*, profile, revision_id, edit=False, lock=False):
    query = ElaboratoRevision.objects.select_related(
        "elaborato__project__workspace", "created_by__user"
    )
    if lock:
        # Nullable author joins must not be locked on PostgreSQL.
        query = query.select_for_update(of=("self",))
    revision = query.filter(pk=revision_id).first()
    if not revision:
        raise HttpError(404, "Revisione non trovata.")
    authorize_revision(profile=profile, revision=revision, edit=edit)
    return revision


def ensure_editable(revision, version):
    if revision.state != "draft":
        raise HttpError(409, "Il documento è pubblicato. Crea una nuova revisione per modificarlo.")
    if revision.version != version:
        raise HttpError(409, "La bozza è cambiata in un'altra finestra. Ricarica prima di salvare.")
    if revision.jobs.filter(state__in=("queued", "running")).exists():
        raise HttpError(
            409, "Attendi il completamento dell'elaborazione prima di modificare la bozza."
        )


def serialize_revision(revision, *, full=False, viewer_can_edit=True):
    document = revision.elaborato
    job = revision.jobs.defer("result", "payload").order_by("-created_at").first() if full else None
    data = {
        "id": str(document.pk),
        "revision_id": str(revision.pk),
        "revision_number": revision.number,
        "version": revision.version,
        "state": revision.state,
        "title": document.title,
        "document_type": document.document_type,
        "project_id": document.project_id,
        "project_name": document.project.name,
        "style": document.style,
        "period_start": document.period_start.isoformat(),
        "period_end": document.period_end.isoformat(),
        "language": document.language,
        "code": f"EL-{document.created_at.year}-{document.number:04d}",
        "author_id": document.created_by_id,
        "author": profile_display_name(document.created_by),
        "updated_at": revision.updated_at.isoformat(),
        "published_at": revision.published_at.isoformat() if revision.published_at else None,
        "pdf_hash": revision.pdf_hash,
        "drive_document_id": revision.drive_document_id,
        "source_count": revision.source_count,
        "job": serialize_job(job) if job else None,
    }
    if full:
        data.update(
            can_edit=viewer_can_edit,
            editor_doc=revision.editor_doc,
            template=revision.template_snapshot,
            evidence=revision.evidence,
            quality=revision.quality,
            declarations=revision.declarations,
            signature_audit=revision.signature_audit,
            preview_ready=bool(
                revision.preview_hash
                and revision.preview_expires_at
                and revision.preview_expires_at > timezone.now()
            ),
            preview_hash=revision.preview_hash,
            preview_signature_applied=bool(revision.preview_signature.get("fingerprint")),
            history=[
                {
                    "revision_id": str(r.pk),
                    "number": r.number,
                    "state": r.state,
                    "published_at": r.published_at.isoformat() if r.published_at else None,
                }
                for r in document.revisions.all()
                if viewer_can_edit or r.state != "draft"
            ],
        )
    return data


def serialize_job(job, *, include_result=False):
    return {
        "id": str(job.pk),
        "revision_id": str(job.revision_id),
        "state": job.state,
        "stage": job.stage,
        "action": job.action,
        "input_version": job.input_version,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "result": job.result if include_result and job.state == "completed" else None,
    }


def list_elaborati(
    *,
    profile,
    q="",
    project_id=None,
    document_type="",
    state="",
    author_id=None,
    start=None,
    end=None,
    offset=0,
    limit=30,
):
    accessible = project_access_queryset(profile)
    query = Elaborato.objects.filter(project__in=accessible).select_related(
        "project", "created_by__user"
    )
    if q:
        query = query.filter(Q(title__icontains=q[:150]) | Q(project__name__icontains=q[:150]))
    if project_id:
        query = query.filter(project_id=project_id)
    if document_type:
        query = query.filter(document_type=document_type)
    if author_id:
        query = query.filter(created_by_id=author_id)
    if start:
        query = query.filter(period_end__gte=start)
    if end:
        query = query.filter(period_start__lte=end)
    # Filter BEFORE pagination; inaccessible drafts never affect the count.
    from django.db.models import OuterRef, Subquery
    from edilcloud.modules.projects.models import ProjectMember

    members = ProjectMember.objects.filter(
        project__in=accessible, profile=profile, disabled=False, status=ProjectMemberStatus.ACTIVE
    ).select_related("project", "profile")
    editable_ids = [m.project_id for m in members if can_edit_project(m)]
    revisions = ElaboratoRevision.objects.filter(elaborato_id=OuterRef("pk")).filter(
        ~Q(state="draft") | Q(elaborato__project_id__in=editable_ids)
    )
    # Global page shows the current revision. Older revisions remain in history;
    # a state filter can explicitly retrieve a superseded publication.
    if state:
        revisions = revisions.filter(state=state)
    revisions = revisions.order_by("-number")
    query = query.annotate(visible_revision=Subquery(revisions.values("pk")[:1])).filter(
        visible_revision__isnull=False
    )
    total = query.count()
    page = list(
        query.order_by("-updated_at", "-pk")[
            max(0, offset) : max(0, offset) + min(max(limit, 1), 60)
        ]
    )
    ids = [d.visible_revision for d in page]
    by_id = {
        str(r.pk): r
        for r in ElaboratoRevision.objects.filter(pk__in=ids)
        .defer(
            "editor_doc",
            "evidence",
            "reasoning",
            "quality",
            "declarations",
            "preview_signature",
            "signature_audit",
        )
        .select_related("elaborato__project", "elaborato__created_by__user")
    }
    return {
        "items": [serialize_revision(by_id[str(d.visible_revision)]) for d in page],
        "total": total,
        "offset": max(0, offset),
        "has_more": offset + len(page) < total,
    }


@transaction.atomic
def create_elaborato(*, profile, payload):
    type(profile).objects.select_for_update().get(pk=profile.pk)
    normalized = payload.model_dump(mode="json")
    fingerprint = digest(normalized)
    prior = Elaborato.objects.filter(
        created_by=profile, creation_key=payload.idempotency_key
    ).first()
    if prior:
        if prior.creation_hash != fingerprint:
            raise HttpError(409, "La chiave di creazione è già associata a un altro elaborato.")
        revision = prior.revisions.get(number=0)
        authorize_revision(profile=profile, revision=revision, edit=True)
        return revision
    try:
        project = get_project_for_profile(profile=profile, project_id=payload.project_id)
    except ValueError as exc:
        raise HttpError(404, "Cantiere non accessibile.") from exc
    require_project_editor(profile, project)
    project = Project.objects.select_for_update().get(pk=project.pk)
    # Same project/profile request may have waited on the project row lock.
    prior = Elaborato.objects.filter(
        created_by=profile, creation_key=payload.idempotency_key
    ).first()
    if prior:
        if prior.creation_hash != fingerprint:
            raise HttpError(409, "Chiave di creazione già utilizzata.")
        return prior.revisions.get(number=0)
    if (
        payload.period_end < payload.period_start
        or (payload.period_end - payload.period_start).days > 366
    ):
        raise HttpError(400, "Seleziona un periodo valido non superiore a un anno.")
    template = template_for(payload.document_type, payload.language)
    if payload.document_type == "daily_report" and payload.period_end != payload.period_start:
        raise HttpError(400, "Il rapporto giornaliero si riferisce a una sola giornata.")
    default = WorkspaceDocumentStyle.objects.filter(workspace=profile.workspace).first()
    style = payload.style or (default.style if default else "corporate")
    document = Elaborato.objects.create(
        project=project,
        created_by=profile,
        document_type=payload.document_type,
        title=f"{template['label']} · {project.name}"[:255],
        period_start=payload.period_start,
        period_end=payload.period_end,
        language=payload.language,
        style=style,
        context=payload.context,
        number=(Elaborato.objects.filter(project=project).aggregate(n=Max("number"))["n"] or 0) + 1,
        creation_key=payload.idempotency_key,
        creation_hash=fingerprint,
    )
    revision = ElaboratoRevision.objects.create(
        elaborato=document, created_by=profile, template_snapshot=template
    )
    queue_job(revision=revision, profile=profile, action="generate", key=payload.idempotency_key)
    DocumentAudit.objects.create(revision=revision, actor=profile, action="created")
    return revision


@transaction.atomic
def save_revision(*, profile, revision_id, payload):
    revision = get_revision(profile=profile, revision_id=revision_id, edit=True, lock=True)
    ensure_editable(revision, payload.version)
    validate_editor(payload.editor_doc, revision.evidence, revision.template_snapshot)
    revision.editor_doc = payload.editor_doc
    revision.version += 1
    revision.quality = {"passed": False, "needs_verification": True}
    invalidate_preview(revision)
    revision.save()
    DocumentAudit.objects.create(
        revision=revision,
        actor=profile,
        action="draft.saved",
        detail={"version": revision.version, "content_hash": digest(revision.editor_doc)},
    )
    return revision


def invalidate_preview(revision):
    revision.preview_hash = ""
    revision.preview_content_hash = ""
    revision.preview_expires_at = None
    revision.preview_signature = {}


@transaction.atomic
def request_action(*, profile, revision_id, payload):
    type(profile).objects.select_for_update().get(pk=profile.pk)
    revision = get_revision(profile=profile, revision_id=revision_id, edit=True, lock=True)
    # Duplicate submissions must remain idempotent even while their job runs.
    prior = DocumentJob.objects.filter(
        requested_by=profile, idempotency_key=payload.idempotency_key
    ).first()
    if not prior:
        ensure_editable(revision, payload.version)
    elif prior.revision_id != revision.pk:
        raise HttpError(409, "Chiave già utilizzata per un altro elaborato.")
    if payload.version != revision.version and not prior:
        raise HttpError(409, "La bozza è cambiata.")
    if payload.action != "generate" and not revision.editor_doc:
        raise HttpError(400, "Attendi la prima redazione prima di usare questa azione.")
    job_payload = payload.model_dump(mode="json", exclude={"idempotency_key", "version"})
    if payload.action == "preview" and payload.apply_signature:
        signature = PersonalSignature.objects.filter(user=profile.user).first()
        if prior:
            job_payload["signature_fingerprint"] = prior.payload.get("signature_fingerprint")
            return queue_job(
                revision=revision,
                profile=profile,
                action=payload.action,
                key=payload.idempotency_key,
                payload=job_payload,
                input_version=payload.version,
            )
        if not signature:
            raise HttpError(400, "Registra la tua firma prima di applicarla.")
        if not payload.signature_confirmation:
            raise HttpError(400, "Conferma esplicitamente la firma di questa revisione.")
        job_payload["signature_fingerprint"] = signature.fingerprint
    return queue_job(
        revision=revision,
        profile=profile,
        action=payload.action,
        key=payload.idempotency_key,
        payload=job_payload,
        input_version=payload.version,
    )


@transaction.atomic
def accept_proposal(*, profile, revision_id, version, job_id):
    revision = get_revision(profile=profile, revision_id=revision_id, edit=True, lock=True)
    ensure_editable(revision, version)
    job = DocumentJob.objects.filter(
        pk=job_id, revision=revision, requested_by=profile, state="completed", input_version=version
    ).first()
    if not job or not job.result.get("requires_acceptance"):
        raise HttpError(409, "Proposta scaduta o non disponibile per questa revisione.")
    validate_editor(job.result["editor_doc"], job.result["evidence"], revision.template_snapshot)
    revision.editor_doc = job.result["editor_doc"]
    revision.evidence = job.result["evidence"]
    revision.source_count = len(revision.evidence.get("sources", []))
    revision.version += 1
    revision.quality = {"passed": False, "needs_verification": True}
    invalidate_preview(revision)
    revision.save()
    DocumentAudit.objects.create(
        revision=revision,
        actor=profile,
        action="proposal.accepted",
        detail={"job_id": str(job.pk), "version": revision.version},
    )
    return revision


@transaction.atomic
def add_declaration(*, profile, revision_id, version, text):
    revision = get_revision(profile=profile, revision_id=revision_id, edit=True, lock=True)
    ensure_editable(revision, version)
    if not text.strip() or len(revision.declarations) >= 100:
        raise HttpError(400, "Dichiarazione vuota o limite raggiunto.")
    declaration = {
        "id": str(uuid.uuid4()),
        "text": text.strip(),
        "author": profile_display_name(profile),
        "profile_id": profile.pk,
        "at": timezone.now().isoformat(),
    }
    revision.declarations = [*revision.declarations, declaration]
    from .evidence import build_evidence

    revision.evidence = build_evidence(
        profile=profile, elaborato=revision.elaborato, declarations=revision.declarations
    )
    revision.source_count = len(revision.evidence.get("sources", []))
    revision.version += 1
    revision.quality = {"passed": False, "needs_verification": True}
    invalidate_preview(revision)
    revision.save()
    DocumentAudit.objects.create(
        revision=revision,
        actor=profile,
        action="declaration.added",
        detail={"declaration_id": declaration["id"]},
    )
    return revision


@transaction.atomic
def new_revision(*, profile, revision_id):
    original = get_revision(profile=profile, revision_id=revision_id, edit=True)
    document = Elaborato.objects.select_for_update().get(pk=original.elaborato_id)
    original.refresh_from_db()
    existing = document.revisions.filter(state="draft").first()
    if existing:
        return existing
    if original.state not in {"published", "signed"}:
        raise HttpError(409, "La nuova revisione deve partire dalla pubblicazione corrente.")
    revision = ElaboratoRevision.objects.create(
        elaborato=document,
        created_by=profile,
        number=(document.revisions.aggregate(n=Max("number"))["n"] or 0) + 1,
        template_snapshot=original.template_snapshot,
        editor_doc=original.editor_doc,
        evidence=original.evidence,
        reasoning=original.reasoning,
        declarations=original.declarations,
        source_count=original.source_count,
        quality={"passed": False, "needs_verification": True},
    )
    # No PDF, signature audit, preview or consent is ever copied.
    DocumentAudit.objects.create(
        revision=revision,
        actor=profile,
        action="revision.created",
        detail={"from_revision": str(original.pk)},
    )
    return revision


def save_signature(*, user, strokes):
    if not isinstance(strokes, list) or not strokes or len(strokes) > 100:
        raise HttpError(400, "Tracciato della firma non valido.")
    total = 0
    for stroke in strokes:
        if not isinstance(stroke, list) or len(stroke) < 2:
            raise HttpError(400, "Ogni tratto deve contenere almeno due punti.")
        total += len(stroke)
        for point in stroke:
            if (
                not isinstance(point, list)
                or len(point) != 2
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
                    for v in point
                )
            ):
                raise HttpError(400, "Coordinate della firma non valide.")
    if total > 8000 or total < 4:
        raise HttpError(400, "Firma vuota o troppo complessa.")
    image = Image.new("RGBA", (1200, 400), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    for stroke in strokes:
        draw.line(
            [(int(x * 1160) + 20, int(y * 360) + 20) for x, y in stroke],
            fill=(24, 39, 35, 255),
            width=5,
            joint="curve",
        )
    output = io.BytesIO()
    image.save(output, "PNG", optimize=True)
    with transaction.atomic():
        # Serialize enrollment per user, including first-time creation.
        type(user).objects.select_for_update().get(pk=user.pk)
        signature, _ = PersonalSignature.objects.get_or_create(
            user=user, defaults={"fingerprint": digest(strokes)}
        )
        old_name = signature.image.name
        signature.strokes = strokes
        signature.fingerprint = digest(strokes)
        signature.image.save(f"{uuid.uuid4()}.png", ContentFile(output.getvalue()), save=False)
        signature.save()
        if old_name:
            transaction.on_commit(lambda: signature.image.storage.delete(old_name))
    return signature
