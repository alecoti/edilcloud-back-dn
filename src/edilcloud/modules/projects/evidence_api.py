"""UUID-based evidence access always rechecks current project membership."""

import hashlib
import mimetypes
from copy import deepcopy
from uuid import UUID

from django.http import FileResponse
from django.db import transaction
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from edilcloud.modules.identity.auth import JWTAuth
from .participations import (
    list_participations,
    create_participation,
    close_participation,
    context,
    parse_at,
    serialize_participation,
    actor_snapshot,
)
from .provenance import digest
from .provenance_models import ProjectSource, ProjectSourceVersion
from .provenance_schemas import (
    ParticipationRequest,
    CloseParticipationRequest,
    EvidenceMetadataRequest,
)
from .services import get_current_profile

router = Router(tags=["project-evidence"], auth=JWTAuth())


def profile_for(request):
    return get_current_profile(user=request.auth.user, claims=request.auth.claims)


@router.get("/{project_id}/participants")
def participants(request, project_id: int):
    return list_participations(profile=profile_for(request), project_id=project_id)


@router.post("/{project_id}/participants")
def add_participant(request, project_id: int, payload: ParticipationRequest):
    return create_participation(
        profile=profile_for(request), project_id=project_id, payload=payload
    )


@router.post("/{project_id}/participants/{participation_id}/close")
def end_participation(
    request, project_id: int, participation_id: UUID, payload: CloseParticipationRequest
):
    return close_participation(
        profile=profile_for(request),
        project_id=project_id,
        participation_id=participation_id,
        valid_to=payload.valid_to,
    )


def get_source_version(request, source_uuid, checksum):
    source = ProjectSource.objects.select_related("project").filter(pk=source_uuid).first()
    if not source:
        raise HttpError(404, "Evidenza non disponibile.")
    context(profile_for(request), source.project_id)
    versions = source.versions.select_related("file_blob", "original_blob")
    version = (
        versions.filter(hash=checksum).first()
        if checksum
        else versions.order_by("-created_at").first()
    )
    if not version:
        raise HttpError(404, "Versione dell'evidenza non disponibile.")
    if digest(version.snapshot) != version.hash:
        raise HttpError(409, "L'integrità della versione non è verificabile.")
    return source, version


@router.post("/evidence/{source_uuid}/metadata")
@transaction.atomic
def update_evidence_metadata(request, source_uuid: UUID, payload: EvidenceMetadataRequest):
    source, row = get_source_version(request, source_uuid, payload.version)
    profile = profile_for(request)
    context(profile, source.project_id, edit=True)
    # Serialise amendments so two editors cannot overwrite each other's metadata.
    ProjectSource.objects.select_for_update().get(pk=source.pk)
    if source.versions.order_by("-created_at").first().pk != row.pk:
        raise HttpError(409, "L'evidenza è cambiata. Ricarica prima di modificarla.")
    snapshot = deepcopy(row.snapshot)
    metadata = snapshot.setdefault("capture_metadata", {})
    date = parse_at(payload.declared_content_date)
    metadata.update(
        declared_content_date=date.isoformat() if date else "", area=payload.area.strip()
    )
    photographer = None
    if payload.photographer_participation_id:
        participant = (
            source.project.participations.select_related("person")
            .filter(pk=payload.photographer_participation_id)
            .first()
        )
        if not participant:
            raise HttpError(404, "Autore non presente nell'anagrafica del cantiere.")
        if date and (
            date < participant.valid_from or (participant.valid_to and date >= participant.valid_to)
        ):
            raise HttpError(400, "Seleziona l'incarico valido alla data del contenuto dichiarata.")
        photographer = serialize_participation(participant)
    metadata["photographer"] = photographer
    related = list(
        ProjectSource.objects.filter(project=source.project, pk__in=payload.related_sources)
    )
    if len(related) != len(set(payload.related_sources)):
        raise HttpError(400, "I collegamenti devono appartenere allo stesso cantiere.")
    metadata["related_sources"] = [
        {"source_uuid": str(item.pk), "reference": item.reference, "kind": item.kind}
        for item in related
    ]
    metadata["declared_by"] = actor_snapshot(
        project=source.project, profile=profile, at=timezone.now()
    )
    metadata["declared_at"] = timezone.now().isoformat()
    updated = ProjectSourceVersion.objects.create(
        source=source,
        snapshot=snapshot,
        hash=digest(snapshot),
        file_blob=row.file_blob,
        original_blob=row.original_blob,
        filename=row.filename,
        original_state=row.original_state,
    )
    return {
        "source_uuid": str(source.pk),
        "version_hash": updated.hash,
        "reference": source.reference,
    }


@router.get("/evidence/{source_uuid}")
def evidence(request, source_uuid: UUID, version: str = ""):
    source, row = get_source_version(request, source_uuid, version)
    _, can_manage = context(profile_for(request), source.project_id)
    latest = source.versions.order_by("-created_at").first()
    content = {
        key: value
        for key, value in row.snapshot["object"].items()
        if not key.endswith("_id") and key not in {"profile_id", "person_id", "company_id"}
    }
    return {
        "source_uuid": str(source.pk),
        "reference": source.reference,
        "kind": source.kind,
        "project_id": source.project_id,
        "project_name": source.project.name,
        "version_hash": row.hash,
        "actor": row.snapshot["actor"],
        "content": content,
        "recorded_at": source.recorded_at.isoformat(),
        "filename": row.filename,
        "original_filename": row.snapshot.get("capture_metadata", {}).get(
            "original_filename", row.filename
        ),
        "capture_metadata": row.snapshot.get("capture_metadata", {}),
        "relations": row.snapshot.get("relations", []),
        "original_state": row.original_state,
        "file_sha256": row.snapshot.get("file_sha256", ""),
        "original_sha256": row.snapshot.get("original_sha256", ""),
        "has_file": bool(row.file_blob_id),
        "has_original": bool(row.original_blob_id),
        "version_recorded_at": row.created_at.isoformat(),
        "manifest_verified": True,
        "can_manage": can_manage,
        "is_latest": row.pk == latest.pk,
        "latest_version_hash": latest.hash,
    }


@router.get("/evidence/{source_uuid}/file")
def evidence_file(request, source_uuid: UUID, version: str, original: bool = False):
    _, row = get_source_version(request, source_uuid, version)
    blob = row.original_blob if original else row.file_blob
    if not blob:
        raise HttpError(404, "File conservato non disponibile.")
    with blob.file.open("rb") as incoming:
        if hashlib.file_digest(incoming, "sha256").hexdigest() != blob.sha256:
            raise HttpError(409, "Il file non corrisponde all'hash conservato.")
    filename = (
        row.snapshot.get("capture_metadata", {}).get("original_filename", row.filename)
        if original
        else row.filename
    )
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    response = FileResponse(
        blob.file.open("rb"),
        filename=filename,
        content_type=mime,
        as_attachment=original
        or mime not in {"image/jpeg", "image/png", "image/webp", "application/pdf"},
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Content-SHA256"] = blob.sha256
    return response
