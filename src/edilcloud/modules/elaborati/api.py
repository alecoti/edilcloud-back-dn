from datetime import date
from uuid import UUID

from django.http import FileResponse, JsonResponse
from ninja import Router
from ninja.errors import HttpError

from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.modules.projects.services import (
    can_edit_project,
    get_current_profile,
    project_access_queryset,
)

from . import schemas, services
from .models import DocumentJob, PersonalSignature, WorkspaceDocumentStyle
from .registry import STYLES, TYPES, template_for

router = Router(tags=["Elaborati"], auth=JWTAuth())


def profile_for(request):
    if not hasattr(request, "_elaborati_profile"):
        request._elaborati_profile = get_current_profile(user=request.auth.user, claims=request.auth.claims)
    return request._elaborati_profile


def revision_response(request, revision, *, editable=True):
    profile = profile_for(request)
    return services.serialize_revision(revision, full=True, viewer_can_edit=editable,
                                       viewer_user_id=profile.user_id, viewer_profile_id=profile.pk)


@router.get("/options")
def options(request):
    profile = profile_for(request)
    projects = project_access_queryset(profile).order_by("name", "pk")
    from edilcloud.modules.projects.models import ProjectMember, ProjectMemberStatus

    memberships = ProjectMember.objects.filter(
        project__in=projects, profile=profile, status=ProjectMemberStatus.ACTIVE, disabled=False
    ).select_related("project", "profile")
    editable = {m.project_id for m in memberships if can_edit_project(m)}
    default = WorkspaceDocumentStyle.objects.filter(workspace=profile.workspace).first()
    # Derive the author filter from visible documents; don't expose a global
    # directory of accounts to a member of one construction site.
    from django.db.models import Exists, OuterRef, Q
    from .models import ElaboratoRevision
    from .visibility import organization_documents

    visible_revisions = ElaboratoRevision.objects.filter(elaborato_id=OuterRef("pk")).exclude(
        state="deleted"
    ).filter(~Q(state="draft") | Q(elaborato__project_id__in=editable))
    authors = (
        organization_documents(
            profile=profile, queryset=services.Elaborato.objects.filter(project__in=projects),
        ).alias(_visible_revision=Exists(visible_revisions)).filter(_visible_revision=True)
        .order_by("created_by_id")
        .values("created_by_id", "created_by__first_name", "created_by__last_name")
        .distinct()
    )
    return {
        "templates": [template_for(k, profile.user.language or "it") for k in TYPES],
        "styles": list(STYLES),
        "default_style": default.style if default else "corporate",
        "can_set_workspace_style": profile.role in {"o", "d"},
        "projects": [
            {"id": p.pk, "name": p.name, "can_create": p.pk in editable} for p in projects
        ],
        "authors": [
            {
                "id": a["created_by_id"],
                "name": f"{a['created_by__first_name']} {a['created_by__last_name']}".strip(),
            }
            for a in authors
        ],
        "signature_enrolled": PersonalSignature.objects.filter(user=profile.user).exists(),
    }


@router.get("")
def list_documents(
    request,
    q: str = "",
    project_id: int | None = None,
    document_type: str = "",
    state: str = "",
    author_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    offset: int = 0,
    limit: int = 30,
):
    return services.list_elaborati(
        profile=profile_for(request),
        q=q,
        project_id=project_id,
        document_type=document_type,
        state=state,
        author_id=author_id,
        start=start,
        end=end,
        offset=offset,
        limit=limit,
    )


@router.post("")
def create(request, payload: schemas.CreateRequest):
    return revision_response(request,
        services.create_elaborato(profile=profile_for(request), payload=payload),
    )


@router.get("/revisions/{revision_id}")
def get_revision(request, revision_id: UUID):
    profile = profile_for(request)
    revision = services.get_revision(profile=profile, revision_id=revision_id)
    from edilcloud.modules.projects.services import get_project_membership

    editable = can_edit_project(get_project_membership(revision.elaborato.project, profile))
    return revision_response(request, revision, editable=editable)


@router.patch("/revisions/{revision_id}")
def save(request, revision_id: UUID, payload: schemas.SaveRequest):
    try:
        revision = services.save_revision(
            profile=profile_for(request), revision_id=revision_id, payload=payload
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return revision_response(request, revision)


@router.post("/revisions/{revision_id}/ownership")
def confirm_ownership(request, revision_id: UUID, payload: schemas.OwnershipConfirmationRequest):
    from .ownership import confirm_legacy

    revision = confirm_legacy(profile=profile_for(request), revision_id=revision_id,
        version=payload.version, confirmed=payload.confirmed, reason=payload.reason)
    return revision_response(request, revision)


@router.post("/revisions/{revision_id}/actions")
def action(request, revision_id: UUID, payload: schemas.ActionRequest):
    return services.serialize_job(
        services.request_action(
            profile=profile_for(request), revision_id=revision_id, payload=payload
        )
    )


@router.delete("/revisions/{revision_id}")
def delete_draft(request, revision_id: UUID, version: int):
    return services.delete_draft(
        profile=profile_for(request), revision_id=revision_id, version=version
    )


@router.post("/revisions/{revision_id}/accept")
def accept(request, revision_id: UUID, payload: schemas.AcceptRequest):
    revision = services.accept_proposal(
        profile=profile_for(request),
        revision_id=revision_id,
        version=payload.version,
        job_id=payload.job_id,
    )
    return revision_response(request, revision)


@router.post("/revisions/{revision_id}/declarations")
def declaration(request, revision_id: UUID, payload: schemas.DeclarationRequest):
    if not payload.confirmed:
        raise HttpError(400, "Conferma esplicitamente che si tratta di una tua dichiarazione.")
    revision = services.add_declaration(
        profile=profile_for(request),
        revision_id=revision_id,
        version=payload.version,
        text=payload.text,
    )
    return revision_response(request, revision)


@router.post("/revisions/{revision_id}/new-revision")
def new_revision(request, revision_id: UUID):
    return revision_response(request,
        services.new_revision(profile=profile_for(request), revision_id=revision_id),
    )


@router.post("/revisions/{revision_id}/publish")
def publish(request, revision_id: UUID, payload: schemas.PublishRequest):
    from .publication import publish_revision

    try:
        revision = publish_revision(
            profile=profile_for(request),
            revision_id=revision_id,
            version=payload.version,
            preview_hash=payload.preview_hash,
            confirm_signature=payload.confirm_signature,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return revision_response(request, revision)


@router.get("/jobs/{job_id}")
def job_status(request, job_id: UUID):
    profile = profile_for(request)
    job = DocumentJob.objects.select_related("revision__elaborato").filter(pk=job_id).first()
    if not job:
        raise HttpError(404, "Elaborazione non trovata.")
    services.authorize_revision(profile=profile, revision=job.revision)
    if job.action not in {"generate", "verify", "preview"} and job.requested_by_id != profile.pk:
        raise HttpError(403, "Questa proposta appartiene a un altro autore.")
    return services.serialize_job(
        job, include_result=True, include_thinking=job.requested_by_id == profile.pk
    )


@router.post("/jobs/{job_id}/resume")
def resume_job(request, job_id: UUID, payload: schemas.ResumeRequest):
    job = services.resume_job(profile=profile_for(request), job_id=job_id, version=payload.version)
    return services.serialize_job(job, include_thinking=True)


def private_response(field, filename, *, download=False):
    if not field:
        raise HttpError(404, "PDF non disponibile.")
    return private_pdf(field.storage, field.name, filename, download=download)


def private_pdf(storage, name, filename, *, download=False):
    try:
        opened = storage.open(name, "rb")
    except FileNotFoundError as exc:
        raise HttpError(404, "PDF non disponibile.") from exc
    response = FileResponse(
        opened, content_type="application/pdf", filename=filename, as_attachment=download
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/revisions/{revision_id}/pdf")
def pdf(
    request, revision_id: UUID, download: bool = False,
    purpose: str | None = None, hash: str | None = None,
):
    profile = profile_for(request)
    if purpose is not None and purpose not in {"display", "publication"}:
        raise HttpError(400, "Scopo PDF non valido.")
    revision = services.get_revision(profile=profile, revision_id=revision_id)
    from .pdf_cache import display_pdf, prepared_profile
    from .filenames import pdf_filename
    from .storage import private_document_storage

    display = purpose == "display" or (purpose is None and revision.preview_signature.get("purpose") == "draft")
    cached = display_pdf(revision, user_id=profile.user_id, profile_id=profile.pk) if display else None
    if revision.state == "draft" and cached is None:
        if revision.preview_signature.get("prepared_by_user_id") != profile.user_id:
            raise HttpError(403, "L'anteprima appartiene a un altro autore.")
        if prepared_profile(revision.preview_signature) != profile.pk:
            raise HttpError(403, "L'anteprima appartiene a un altro autore.")
        from django.utils import timezone

        if (
            not revision.preview_hash
            or not revision.preview_expires_at
            or revision.preview_expires_at <= timezone.now()
        ):
            raise HttpError(409, "Genera un'anteprima aggiornata.")
        from .publication import publication_content_hash

        if revision.preview_content_hash != publication_content_hash(revision):
            raise HttpError(409, "Il PDF non corrisponde alla versione corrente della bozza.")
    file_hash = cached.pdf_hash if cached else revision.preview_hash if revision.state == "draft" else revision.pdf_hash
    if hash is not None and hash != file_hash:
        raise HttpError(409, "Il PDF è cambiato. Ricarica il documento.")
    if cached:
        return private_pdf(private_document_storage(), cached.pdf_file, pdf_filename(revision), download=download)
    return private_response(revision.preview_file, pdf_filename(revision), download=download)


@router.get("/revisions/{revision_id}/sources/{source_id}")
def source_file(request, revision_id: UUID, source_id: str, image_preview: bool = False):
    profile = profile_for(request)
    revision = services.get_revision(profile=profile, revision_id=revision_id)
    source = next((s for s in revision.evidence.get("sources", []) if s["id"] == source_id), None)
    if not source:
        raise HttpError(404, "Fonte non disponibile.")
    from .evidence import resolve_evidence_file

    try:
        field = resolve_evidence_file(
            profile=profile, project_id=revision.elaborato.project_id, source=source
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc
    from pathlib import PurePosixPath
    import mimetypes

    name = PurePosixPath(field.name).name
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    if image_preview and source["kind"] in {"photo", "image_attachment"}:
        from .renderer import image_data
        from django.http import HttpResponse
        import base64

        data_url = image_data(field, max_pixels=(1000, 800))
        header, encoded = data_url.split(",", 1)
        response = HttpResponse(
            base64.b64decode(encoded), content_type=header.removeprefix("data:").split(";")[0]
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        return response
    # Untrusted SVG/HTML attachments are downloads, never inline same-origin HTML.
    response = FileResponse(
        field.open("rb"),
        content_type=content_type,
        as_attachment=content_type
        not in {"image/png", "image/jpeg", "image/webp", "application/pdf"},
        filename=name,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/signature")
def signature(request):
    own = PersonalSignature.objects.filter(user=request.auth.user).first()
    return personal_signature_response({
        "enrolled": bool(own),
        "strokes": own.strokes if own else [],
        "fingerprint": own.fingerprint if own else None,
    })


def personal_signature_response(value):
    return JsonResponse(value, headers={
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.put("/signature")
def enroll_signature(request, payload: schemas.SignatureRequest):
    signature = services.save_signature(user=request.auth.user, strokes=payload.strokes)
    return personal_signature_response({"enrolled": True, "fingerprint": signature.fingerprint})


@router.delete("/signature")
def delete_signature(request):
    services.delete_signature(user=request.auth.user)
    return personal_signature_response({"enrolled": False})


@router.put("/workspace-style")
def workspace_style(request, payload: schemas.StyleRequest):
    profile = profile_for(request)
    if profile.role not in {"o", "d"}:
        raise HttpError(403, "Solo il titolare o il delegato può scegliere lo stile del workspace.")
    WorkspaceDocumentStyle.objects.update_or_create(
        workspace=profile.workspace, defaults={"style": payload.style}
    )
    return {"style": payload.style}
