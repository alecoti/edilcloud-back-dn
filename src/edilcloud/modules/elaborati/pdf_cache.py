"""Private derived display artifacts, separate from short-lived publication consent.

Callers authorize the revision before resolving a cache entry. Writes hold the
revision lock and the durable worker fence; cleanup runs only after commit.
"""

from dataclasses import dataclass
import logging

from django.db import connection, transaction
from django.utils import timezone

from edilcloud.modules.workspaces.models import Profile
from .models import DraftPdfCache, ElaboratoRevision, PersonalSignature
from .storage import private_document_storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Artifact:
    pdf_file: str
    pdf_hash: str


def viewer_profile(user_id, profile_id=None):
    if type(user_id) is not int:
        return None
    if type(profile_id) is int:
        return (
            Profile.objects.filter(pk=profile_id, user_id=user_id)
            .values_list("pk", flat=True)
            .first()
        )
    if profile_id is not None:
        return None
    ids = list(Profile.objects.filter(user_id=user_id).values_list("pk", flat=True)[:2])
    return ids[0] if len(ids) == 1 else None


def prepared_profile(audit):
    return viewer_profile(audit.get("prepared_by_user_id"), audit.get("prepared_by_profile_id"))


def unsigned_draft(revision):
    audit = revision.preview_signature
    return bool(
        audit.get("purpose") == "draft"
        and not audit.get("fingerprint")
        and revision.preview_file
        and revision.preview_hash
        and revision.preview_content_hash
    )


def file_exists(name):
    storage = private_document_storage()
    try:
        return bool(name and storage.exists(name) and storage.size(name) > 0)
    except FileNotFoundError:
        return False


def display_pdf(revision, *, user_id, profile_id=None):
    if revision.state != "draft":
        return None
    profile_id = viewer_profile(user_id, profile_id)
    if profile_id is None:
        return None
    from .publication import publication_content_hash

    content_hash = publication_content_hash(revision)
    cache = DraftPdfCache.objects.filter(
        revision=revision, profile_id=profile_id, content_hash=content_hash
    ).first()
    if cache and file_exists(cache.pdf_file):
        return Artifact(cache.pdf_file, cache.pdf_hash)
    if (
        unsigned_draft(revision)
        and revision.preview_content_hash == content_hash
        and revision.preview_signature.get("prepared_by_user_id") == user_id
        and prepared_profile(revision.preview_signature) == profile_id
        and file_exists(revision.preview_file.name)
    ):
        return Artifact(revision.preview_file.name, revision.preview_hash)
    return None


def preserve_display_pdf(revision):
    if unsigned_draft(revision):
        profile_id = prepared_profile(revision.preview_signature)
        if profile_id is not None:
            DraftPdfCache.objects.get_or_create(
                revision=revision,
                profile_id=profile_id,
                defaults={
                    "content_hash": revision.preview_content_hash,
                    "pdf_file": revision.preview_file.name,
                    "pdf_hash": revision.preview_hash,
                    "created_at": revision.updated_at,
                },
            )


def record_display_pdf(revision, *, profile_id):
    if not unsigned_draft(revision):
        return
    from .publication import publication_content_hash

    if (
        revision.preview_content_hash != publication_content_hash(revision)
        or revision.preview_signature.get("prepared_by_profile_id") != profile_id
    ):
        raise ValueError("Il PDF di lettura non corrisponde alla bozza o al profilo richiedente.")
    old = DraftPdfCache.objects.filter(revision=revision, profile_id=profile_id).first()
    DraftPdfCache.objects.update_or_create(
        revision=revision,
        profile_id=profile_id,
        defaults={
            "content_hash": revision.preview_content_hash,
            "pdf_file": revision.preview_file.name,
            "pdf_hash": revision.preview_hash,
            "created_at": timezone.now(),
        },
    )
    if old and old.pdf_file != revision.preview_file.name:
        schedule_cleanup(old.pdf_file)


def legacy_files():
    if connection.vendor != "postgresql":
        return set()
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('edilcloud_runtime.elaborati_draft_pdf_cache')")
        if cursor.fetchone()[0] is None:
            return set()
        cursor.execute("SELECT pdf_file FROM edilcloud_runtime.elaborati_draft_pdf_cache")
        return {row[0] for row in cursor.fetchall()}


def referenced_files():
    result = set(
        ElaboratoRevision.objects.exclude(preview_file="").values_list("preview_file", flat=True)
    )
    result.update(DraftPdfCache.objects.values_list("pdf_file", flat=True))
    result.update(PersonalSignature.objects.exclude(image="").values_list("image", flat=True))
    return result | legacy_files()


def delete_unreferenced_pdf(name):
    try:
        if (
            not ElaboratoRevision.objects.filter(preview_file=name).exists()
            and not DraftPdfCache.objects.filter(pdf_file=name).exists()
            and name not in legacy_files()
        ):
            private_document_storage().delete(name)
    except Exception:
        logger.warning("Deferred unreferenced document PDF cleanup")


def schedule_cleanup(name):
    if name:
        transaction.on_commit(lambda: delete_unreferenced_pdf(name), robust=True)


def remove_display_pdfs(revision):
    names = list(DraftPdfCache.objects.filter(revision=revision).values_list("pdf_file", flat=True))
    DraftPdfCache.objects.filter(revision=revision).delete()
    for name in names:
        schedule_cleanup(name)
