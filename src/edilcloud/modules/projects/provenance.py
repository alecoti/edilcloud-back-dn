"""Deterministic identity, attribution and content-addressed evidence storage."""

from copy import deepcopy
from contextlib import nullcontext
import hashlib
import json
from pathlib import PurePosixPath

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.db.models import Max
from django.db.models.fields.files import FieldFile
from django.utils import timezone

from .provenance_models import EvidenceBlob, ProjectSource, ProjectSourceVersion
from .participations import actor_snapshot, role_labels

PREFIXES = {
    "post": "P",
    "comment": "C",
    "post_attachment": "A",
    "comment_attachment": "A",
    "photo": "F",
    "document": "D",
    "drawing_pin": "T",
    "model_pin": "B",
    "model": "M",
    "member": "R",
    "participation": "R",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def snapshot_blob(project, field, *, check_quota=True):
    """Stream without a large in-memory copy; deduplicate only within a project."""
    if not field:
        return None
    opened = field.open("rb")
    with opened if isinstance(field, FieldFile) else nullcontext(opened) as incoming:
        sha = hashlib.sha256()
        size = 0
        for block in iter(lambda: incoming.read(1024 * 1024), b""):
            sha.update(block)
            size += len(block)
        checksum = sha.hexdigest()
        existing = EvidenceBlob.objects.filter(project=project, sha256=checksum).first()
        if existing:
            return existing
        incoming.seek(0)
        from .models import Project

        with transaction.atomic():
            Project.objects.select_for_update().get(pk=project.pk)
            existing = EvidenceBlob.objects.filter(project=project, sha256=checksum).first()
            if existing:
                return existing
            if check_quota:
                from edilcloud.modules.billing.services import assert_storage_quota_available

                assert_storage_quota_available(project.workspace, incoming_bytes=size)
            blob = EvidenceBlob(project=project, sha256=checksum, size=size)
            suffix = PurePosixPath(getattr(field, "name", "")).suffix.lower()[:12]
            blob.file.save(
                f"{project.pk}/{checksum[:2]}/{checksum}{suffix}", File(incoming), save=False
            )
            blob.save(force_insert=True)
            return blob


def prepare_upload(project, uploaded_file):
    """Keep submitted bytes before resizing, rotating or recompressing anything."""
    from edilcloud.modules.files.media_optimizer import optimize_media_for_storage

    original = snapshot_blob(project, uploaded_file)
    metadata = {"original_filename": PurePosixPath(uploaded_file.name).name}
    try:
        from PIL import Image

        with original.file.open("rb") as retained:
            with Image.open(retained) as image:
                exif = image.getexif()
                capture = exif.get_ifd(34665) if 34665 in exif else {}
                metadata.update(
                    {
                        "exif_datetime_original": str(capture.get(36867) or exif.get(36867) or ""),
                        "exif_offset_original": str(capture.get(36881) or exif.get(36881) or ""),
                        "original_width": image.width,
                        "original_height": image.height,
                    }
                )
    except (OSError, ValueError, TypeError):
        pass
    # PIL can close a file-like input. UploadedFile.open must reopen where supported.
    uploaded_file.open("rb")
    prepared = optimize_media_for_storage(uploaded_file)
    prepared._evidence_original_blob_id = original.pk if original else None
    prepared._evidence_capture_metadata = metadata
    return prepared


def object_context(obj):
    """Only local, known model relations; never trust a client-supplied locator."""
    name = obj._meta.model_name
    if name == "projectpost":
        return obj.project, "post", obj.author, None
    if name == "postcomment":
        return obj.post.project, "comment", obj.author, None
    if name == "postattachment":
        return obj.post.project, "post_attachment", obj.uploaded_by or obj.post.author, obj.file
    if name == "commentattachment":
        return (
            obj.comment.post.project,
            "comment_attachment",
            obj.uploaded_by or obj.comment.author,
            obj.file,
        )
    if name == "projectdocument":
        return obj.project, "document", obj.uploaded_by, obj.document
    if name == "projectphoto":
        return obj.project, "photo", obj.uploaded_by, obj.photo
    if name == "projectdrawingpin":
        return obj.project, "drawing_pin", obj.created_by, None
    if name == "projectmodelpin":
        return obj.project, "model_pin", obj.created_by, None
    if name == "projectmodel3d":
        return obj.project, "model", obj.created_by, obj.file
    if name == "projectmember":
        return obj.project, "member", obj.profile, None
    if name == "projectparticipation":
        return obj.project, "participation", obj.recorded_by, None
    raise ValueError("Tipo di fonte non supportato.")


def object_data(obj, kind):
    if kind == "participation":
        from .participations import serialize_participation

        return {**serialize_participation(obj), "updated_at": obj.updated_at.isoformat()}
    if kind in {"post", "comment"}:
        data = {
            "text": obj.original_text or obj.text,
            "deleted": obj.is_deleted,
            "updated_at": obj.updated_at.isoformat(),
        }
        if kind == "post":
            data.update(
                post_kind=obj.post_kind,
                event_at=obj.published_date.isoformat(),
                activity_id=obj.activity_id,
                task_id=obj.task_id,
            )
        else:
            data.update(post_id=obj.post_id, parent_comment_id=obj.parent_id)
        return data
    if kind == "member":
        return {
            "subject_name": obj.profile.member_name,
            "role_codes": obj.project_role_codes,
            "role_labels": role_labels(obj.project_role_codes),
            "disabled": obj.disabled,
            "status": obj.status,
        }
    data = {
        "title": getattr(obj, "title", ""),
        "description": getattr(obj, "description", ""),
        "updated_at": obj.updated_at.isoformat(),
    }
    for key in (
        "label",
        "page_number",
        "pin_code",
        "x",
        "y",
        "z",
        "post_id",
        "model_id",
        "drawing_document_id",
        "document_kind",
    ):
        if hasattr(obj, key):
            data[key] = getattr(obj, key)
    return data


def related_source_refs(obj, kind):
    """Freeze parent locations using documentary UUIDs, never public numeric IDs."""
    targets = []
    if kind in {"comment", "post_attachment", "drawing_pin", "model_pin"}:
        targets.append(obj.post)
    if kind == "comment_attachment":
        targets.extend((obj.comment, obj.comment.post))
    if kind == "drawing_pin":
        targets.append(obj.drawing_document)
    if kind == "model_pin":
        targets.append(obj.model)
    refs = []
    for target in targets:
        identity, version = capture_source(target, reconstructed=True)
        refs.append(
            {
                "source_uuid": str(identity.pk),
                "reference": identity.reference,
                "version_hash": version.hash,
                "kind": identity.kind,
            }
        )
    return refs


@transaction.atomic
def capture_source(obj, *, reconstructed=False, archive=True):
    from .models import Project

    project, kind, actor, field = object_context(obj)
    source = ProjectSource.objects.filter(
        project=project, kind=kind, record_key=str(obj.pk)
    ).first()
    if not source:
        Project.objects.select_for_update().get(pk=project.pk)
        source = ProjectSource.objects.filter(
            project=project, kind=kind, record_key=str(obj.pk)
        ).first()
        if not source:
            prefix = (
                "F"
                if kind in {"post_attachment", "comment_attachment"}
                and (
                    str(getattr(obj, "content_type", "")).startswith("image/")
                    or PurePosixPath(field.name).suffix.lower()
                    in {".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff"}
                )
                else PREFIXES[kind]
            )
            number = (
                ProjectSource.objects.filter(project=project, prefix=prefix).aggregate(
                    value=Max("number")
                )["value"]
                or 0
            ) + 1
            snapshot = actor_snapshot(
                project=project, profile=actor, at=obj.created_at, reconstructed=reconstructed
            )
            source = ProjectSource.objects.create(
                project=project,
                kind=kind,
                record_key=str(obj.pk),
                prefix=prefix,
                number=number,
                actor_snapshot=snapshot,
                recorded_at=obj.created_at,
                identity_state=snapshot["identity_state"],
            )
    if not archive and source.versions.exists():
        return source, source.versions.order_by("-created_at").first()
    working = original = None
    filename = PurePosixPath(field.name).name if field else ""
    original_state = "not_archived" if field and not archive else ""
    metadata = getattr(obj, "_evidence_capture_metadata", {})
    if field and archive:
        try:
            working = snapshot_blob(project, field)
        except (FileNotFoundError, OSError):
            # Legacy missing files remain represented, never claimed readable.
            original_state = "missing"
        original_id = getattr(obj, "_evidence_original_blob_id", None)
        if original_id:
            original = EvidenceBlob.objects.filter(project=project, pk=original_id).first()
        if original:
            original_state = "received_original"
        elif working:
            previous = (
                None
                if getattr(obj, "_evidence_new_upload", False)
                else source.versions.exclude(original_blob=None)
                .select_related("original_blob")
                .order_by("-created_at")
                .first()
            )
            original = previous.original_blob if previous else working
            original_state = (
                previous.original_state
                if previous
                else ("retained_legacy_copy" if reconstructed else "stored_at_registration")
            )
    data = {
        "object": object_data(obj, kind),
        "actor": deepcopy(source.actor_snapshot),
        "recorded_at": source.recorded_at.isoformat(),
        "filename": filename,
        "file_sha256": working.sha256 if working else "",
        "original_sha256": original.sha256 if original else "",
        "original_state": original_state,
        "capture_metadata": metadata,
        "relations": related_source_refs(obj, kind),
    }
    # Preserve original acquisition metadata across unrelated text/label edits.
    if field and not metadata:
        previous = source.versions.order_by("-created_at").first()
        if previous:
            data["capture_metadata"] = previous.snapshot.get("capture_metadata", {})
    version, _ = ProjectSourceVersion.objects.get_or_create(
        source=source,
        hash=digest(data),
        defaults={
            "snapshot": data,
            "file_blob": working,
            "original_blob": original,
            "filename": filename,
            "original_state": original_state,
        },
    )
    return source, version


def enrich_source(*, project, source):
    """Attach stable provenance to an existing internal evidence contract."""
    ref = source.get("file_ref") or {}
    kind = (
        source.get("provenance_kind")
        or ref.get("model")
        or {"photo": "photo", "drawing": "document"}.get(source["kind"], source["kind"])
    )
    if kind == "project_photo":
        kind = "photo"
    if kind not in PREFIXES:
        return materialized_source(project, source)
    key = str(ref.get("id") or source.get("record_id") or source["id"].split(":", 1)[-1])
    identity = ProjectSource.objects.filter(project=project, kind=kind, record_key=key).first()
    from . import models

    classes = {
        "post": models.ProjectPost,
        "comment": models.PostComment,
        "post_attachment": models.PostAttachment,
        "comment_attachment": models.CommentAttachment,
        "document": models.ProjectDocument,
        "photo": models.ProjectPhoto,
        "drawing_pin": models.ProjectDrawingPin,
        "model_pin": models.ProjectModelPin,
        "model": models.ProjectModel3D,
        "member": models.ProjectMember,
        "participation": models.ProjectParticipation,
    }
    obj = classes[kind].objects.filter(pk=key).first()
    if obj is None or object_context(obj)[0].pk != project.pk:
        raise ValueError("La fonte non appartiene al cantiere dell'elaborato.")
    if not identity:
        identity, version = capture_source(obj, reconstructed=True)
    else:
        version = (
            identity.versions.order_by("-created_at")
            .select_related("file_blob", "original_blob")
            .first()
        )
        if (
            not version
            or version.original_state == "not_archived"
            or version.snapshot["object"] != object_data(obj, kind)
        ):
            identity, version = capture_source(obj, reconstructed=True)
    if not version:
        return source
    source = deepcopy(source)
    source.update(
        source_uuid=str(identity.pk),
        source_version=str(version.pk),
        version_hash=version.hash,
        reference=identity.reference,
        actor=deepcopy(version.snapshot["actor"]),
        recorded_at=version.snapshot["recorded_at"],
        original_state=version.original_state,
        file_sha256=version.snapshot["file_sha256"],
        original_sha256=version.snapshot["original_sha256"],
        capture_metadata=deepcopy(version.snapshot.get("capture_metadata", {})),
    )
    source["relations"] = deepcopy(version.snapshot.get("relations", []))
    source["data"]["source_actor"] = source["actor"]
    if source["kind"] in {"post", "comment"} and source["actor"].get("person_name"):
        source["data"]["author"] = source["actor"]["person_name"]
    if source["kind"] != "member":
        source["data"]["professional_roles"] = source["actor"].get("roles", [])
        source["data"]["professional_role_labels"] = source["actor"].get("role_labels", [])
        source["data"]["company"] = source["actor"].get("company_name", "")
        source["data"]["qualification"] = source["actor"].get("qualification", "")
    source["hash"] = digest({k: v for k, v in source.items() if k not in {"hash", "file_ref"}})
    return source


@transaction.atomic
def materialized_source(project, source):
    """Give contextual/declaration records a stable identity without guessing authorship."""
    from datetime import datetime
    from .models import Project

    allowed = {
        "project": "PR",
        "request": "Q",
        "declaration": "DS",
        "task": "L",
        "activity": "L",
        "event": "E",
        "previous_elaborato": "EL",
    }
    if source["kind"] not in allowed:
        return source
    kind, key = (
        source["kind"],
        str(
            source.get("provenance_key")
            or source.get("record_id")
            or source["id"].split(":", 1)[-1]
        ),
    )
    identity = ProjectSource.objects.filter(project=project, kind=kind, record_key=key).first()
    data = source["data"]
    if not identity:
        Project.objects.select_for_update().get(pk=project.pk)
        identity = ProjectSource.objects.filter(project=project, kind=kind, record_key=key).first()
        if not identity:
            prefix = allowed[kind]
            actor = deepcopy(
                data.get("source_actor")
                or {
                    "person_name": data.get("declared_by", "") if kind == "declaration" else "",
                    "company_name": "",
                    "qualification": "",
                    "roles": [],
                    "role_labels": [],
                    "identity_state": "declared" if kind == "declaration" else "unavailable",
                    "captured_at": timezone.now().isoformat(),
                    "historical_roles_known": False,
                }
            )
            at = datetime.fromisoformat(source["at"]) if source.get("at") else timezone.now()
            if timezone.is_naive(at):
                at = timezone.make_aware(at)
            identity = ProjectSource.objects.create(
                project=project,
                kind=kind,
                record_key=key,
                prefix=prefix,
                number=(
                    ProjectSource.objects.filter(project=project, prefix=prefix).aggregate(
                        value=Max("number")
                    )["value"]
                    or 0
                )
                + 1,
                actor_snapshot=actor,
                identity_state=actor["identity_state"],
                recorded_at=at,
            )
    snapshot = {
        "object": deepcopy(data),
        "actor": deepcopy(data.get("source_actor") or identity.actor_snapshot),
        "recorded_at": identity.recorded_at.isoformat(),
        "file_sha256": "",
        "original_sha256": "",
        "original_state": "",
        "capture_metadata": {},
    }
    version, _ = ProjectSourceVersion.objects.get_or_create(
        source=identity, hash=digest(snapshot), defaults={"snapshot": snapshot}
    )
    return {
        **source,
        "source_uuid": str(identity.pk),
        "source_version": str(version.pk),
        "version_hash": version.hash,
        "reference": identity.reference,
        "actor": snapshot["actor"],
        "recorded_at": snapshot["recorded_at"],
    }


def source_link(source, *, revision_id=None):
    base = str(getattr(settings, "APP_FRONTEND_URL", "https://app.edilcloud.eu")).rstrip("/")
    uuid = source.get("source_uuid")
    if not uuid:
        return ""
    path = f"/evidenze/{uuid}?version={source['version_hash']}"
    if revision_id:
        path += f"&revision={revision_id}"
    return base + path
