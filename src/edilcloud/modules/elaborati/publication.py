import hashlib
import uuid
from datetime import timedelta

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from edilcloud.modules.projects.models import Project, ProjectDocument, ProjectFolder
from edilcloud.modules.projects.services import (
    build_folder_path,
    profile_display_name,
    project_role_label,
    get_project_membership,
)

from .content import digest, validate_editor
from .models import DocumentAudit, Elaborato, ElaboratoRevision, PersonalSignature
from .services import ensure_editable, get_revision


def publication_content_hash(revision):
    d = revision.elaborato
    return digest(
        {
            "editor": revision.editor_doc,
            "evidence": revision.evidence.get("bundle_hash"),
            "template": revision.template_snapshot,
            "title": d.title,
            "period_start": d.period_start,
            "period_end": d.period_end,
            "style": d.style,
            "language": d.language,
        }
    )


def validate_publication(revision):
    """Technical validation only; content review by AI is always optional."""
    validate_editor(revision.editor_doc, revision.evidence, revision.template_snapshot)
    if not revision.editor_doc["content"]:
        raise ValueError("La bozza è vuota. Inserisci il contenuto prima di preparare il PDF.")


def prepare_preview(job):
    from .renderer import image_data, render_pdf

    revision = job.revision
    # Rendering/publication are deterministic operations, never paid AI checks.
    # AI findings remain available in revision.quality for the author's review;
    # the optional Verify command is the only way to request another AI review.
    validate_publication(revision)
    signature = None
    purpose = job.payload.get("preview_purpose", "publication")
    if purpose == "draft" and job.payload.get("apply_signature"):
        raise HttpError(400, "La firma si applica soltanto alla versione finale da confermare.")
    audit = {"prepared_by_user_id": job.requested_by.user_id, "purpose": purpose}
    if job.payload.get("apply_signature"):
        personal = PersonalSignature.objects.filter(user=job.requested_by.user).first()
        if (
            not personal
            or personal.fingerprint != job.payload.get("signature_fingerprint")
            or not job.payload.get("signature_confirmation")
        ):
            raise HttpError(
                409, "La firma è cambiata o la conferma non è valida. Ripeti l'anteprima."
            )
        member = get_project_membership(revision.elaborato.project, job.requested_by)
        audit.update(
            user_id=job.requested_by.user_id,
            profile_id=job.requested_by.pk,
            name=profile_display_name(job.requested_by),
            role=project_role_label(member.role),
            company=job.requested_by.workspace.name,
            fingerprint=personal.fingerprint,
            confirmed_at=timezone.now().isoformat(),
            revision_id=str(revision.pk),
        )
        signature = {**audit, "image_data": image_data(personal.image)}
    from .jobs import set_stage

    set_stage(job, "rendering")
    pdf = render_pdf(
        revision=revision,
        profile=job.requested_by,
        signature=signature,
        publication_state="draft" if purpose == "draft" else "signed" if signature else "published",
    )
    pdf_hash = hashlib.sha256(pdf).hexdigest()
    # FileField.save(save=False) writes an isolated immutable candidate. Only the
    # fenced job completion may attach it to a still-current revision.
    revision.preview_file.save(f"{uuid.uuid4()}.pdf", ContentFile(pdf), save=False)
    return {
        "preview": {
            "preview_file": revision.preview_file.name,
            "preview_hash": pdf_hash,
            "preview_content_hash": publication_content_hash(revision),
            "preview_expires_at": timezone.now() + timedelta(minutes=20),
            "preview_signature": audit,
        },
    }


def folder_chain(project, names):
    parent = None
    for name in names:
        parent, _ = ProjectFolder.objects.get_or_create(
            project=project,
            path=build_folder_path(parent=parent, name=name),
            defaults={"parent": parent, "name": name},
        )
    return parent


@transaction.atomic
def publish_revision(*, profile, revision_id, version, preview_hash, confirm_signature=False):
    revision = get_revision(profile=profile, revision_id=revision_id, edit=True)
    # Serialize across two revisions of the same document and storage quotas.
    Project.objects.select_for_update().get(pk=revision.elaborato.project_id)
    Elaborato.objects.select_for_update().get(pk=revision.elaborato_id)
    revision = get_revision(profile=profile, revision_id=revision_id, edit=True, lock=True)
    # Repeating the exact publish request returns the already-frozen result.
    if revision.state in {"published", "signed"} and revision.pdf_hash == preview_hash:
        return revision
    ensure_editable(revision, version)
    validate_publication(revision)
    if (
        not revision.preview_file
        or revision.preview_hash != preview_hash
        or not revision.preview_expires_at
        or revision.preview_expires_at <= timezone.now()
        or revision.preview_content_hash != publication_content_hash(revision)
    ):
        raise HttpError(409, "L'anteprima è scaduta o non corrisponde più alla bozza.")
    audit = revision.preview_signature
    if audit.get("purpose", "publication") != "publication":
        raise HttpError(409, "Prepara la versione finale prima di confermare la pubblicazione.")
    if audit.get("prepared_by_user_id") != profile.user_id:
        raise HttpError(403, "L'anteprima deve essere confermata dall'utente che l'ha preparata.")
    signed = bool(audit.get("fingerprint"))
    if signed:
        personal = PersonalSignature.objects.filter(user=profile.user).first()
        if (
            not confirm_signature
            or not personal
            or personal.fingerprint != audit["fingerprint"]
            or audit.get("user_id") != profile.user_id
        ):
            raise HttpError(400, "Conferma esplicitamente la tua firma per questa revisione.")
    with revision.preview_file.open("rb") as stream:
        data = stream.read(45 * 1024 * 1024 + 1)
    if len(data) > 45 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != preview_hash:
        raise HttpError(409, "Integrità dell'anteprima non verificata. Genera una nuova anteprima.")
    from edilcloud.modules.billing.services import assert_storage_quota_available

    assert_storage_quota_available(revision.elaborato.project.workspace, incoming_bytes=len(data))
    project = revision.elaborato.project
    folder_names = ["Elaborati pubblicati", *revision.template_snapshot["drive_folder"]]
    folder = folder_chain(project, folder_names)
    if folder.documents.count() >= 50:
        folder = folder_chain(
            project, [*folder_names, str(timezone.now().year), f"{timezone.now().month:02d}"]
        )
    older = revision.elaborato.revisions.filter(state__in=("published", "signed"))
    if older.exists():
        history = folder_chain(
            project, [*folder_names, "Storico", f"EL-{revision.elaborato.number:04d}"]
        )
        for old in older:
            if old.drive_document_id:
                ProjectDocument.objects.filter(pk=old.drive_document_id).update(folder=history)
        older.update(state="superseded")
    code = f"EL-{revision.elaborato.created_at.year}-{revision.elaborato.number:04d}"
    drive = ProjectDocument.objects.create(
        project=project,
        uploaded_by=profile,
        folder=folder,
        title=f"{code} Rev.{revision.number} · {revision.elaborato.title}"[:255],
        description=f"Elaborato pubblicato · SHA-256 {preview_hash}",
        document=ContentFile(data, name=f"{code}-Rev{revision.number}.pdf"),
    )
    revision.drive_document = drive
    revision.pdf_hash = preview_hash
    from .documentary_register import manifest
    revision.frozen_manifest = manifest(revision, pdf_hash=preview_hash)
    revision.published_at = timezone.now()
    revision.published_by = profile
    revision.state = "signed" if signed else "published"
    revision.signature_audit = (
        {**audit, "pdf_hash": preview_hash, "published_at": revision.published_at.isoformat()}
        if signed
        else {}
    )
    revision.save()
    DocumentAudit.objects.create(
        revision=revision,
        actor=profile,
        action="published",
        detail={
            "pdf_hash": preview_hash,
            "signature": revision.signature_audit,
            "drive_document_id": drive.pk,
        },
    )
    # Reuse project realtime + notification policies, including exclusion of self
    # notifications, rather than introducing a second notification system.
    transaction.on_commit(lambda: notify_publication(profile=profile, revision_id=revision.pk))
    return revision


def notify_publication(*, profile, revision_id):
    import logging

    try:
        revision = ElaboratoRevision.objects.select_related(
            "elaborato__project", "drive_document__folder"
        ).get(pk=revision_id)
        from edilcloud.modules.projects.services import emit_project_realtime_event

        emit_project_realtime_event(
            event_type="document.created",
            project_id=revision.elaborato.project_id,
            actor_profile=profile,
            document_id=revision.drive_document_id,
            folder_id=revision.drive_document.folder_id,
            data={
                "category": "document",
                "project_level": True,
                "document_title": revision.elaborato.title,
                "elaborato_revision_id": str(revision.pk),
            },
        )
        from edilcloud.modules.projects.services import (
            notify_profiles_with_blueprint,
            project_notification_recipients,
            build_project_document_notification,
        )

        notify_profiles_with_blueprint(
            recipients=project_notification_recipients(
                revision.elaborato.project, exclude_profile_ids={profile.pk}
            ),
            actor_profile=profile,
            blueprint=build_project_document_notification(
                kind="project.document.created",
                action="created",
                actor_profile=profile,
                project=revision.elaborato.project,
                document_id=revision.drive_document_id,
                document_title=revision.elaborato.title,
                folder_id=revision.drive_document.folder_id,
                folder_path=revision.drive_document.folder.path,
                file_field=revision.drive_document.document,
            ),
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "Publication realtime failed revision_id=%s", revision_id
        )
