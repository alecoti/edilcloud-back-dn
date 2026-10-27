"""Bounded cleanup of unreferenced engine artifacts, never project media."""

import re
from datetime import timedelta
from pathlib import Path
import uuid

from django.core.files.storage import FileSystemStorage
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.db import connection, transaction
from django.utils import timezone

from .storage import private_document_storage


def cleanup_stale_display_cache(*, dry_run=True, limit=200):
    """Retire only cache metadata of non-draft revisions, never their frozen PDF."""
    from .models import DraftPdfCache, ElaboratoRevision
    from .pdf_cache import schedule_cleanup

    limit = max(0, min(limit, 200))
    if not limit:
        return []
    candidates = list(
        DraftPdfCache.objects.exclude(revision__state="draft")
        .order_by("revision_id", "profile_id")
        .values_list("revision_id", "profile_id")[:limit]
    )
    removed = []
    for revision_id, profile_id in candidates:
        with transaction.atomic():
            revision = (
                ElaboratoRevision.objects.select_for_update(
                    skip_locked=connection.vendor == "postgresql"
                ).filter(pk=revision_id).exclude(state="draft").first()
            )
            if revision is None:
                continue
            cache = DraftPdfCache.objects.filter(
                revision_id=revision_id, profile_id=profile_id
            ).first()
            if cache is None:
                continue
            removed.append({"revision_id": str(revision_id), "profile_id": profile_id,
                            "pdf_file": cache.pdf_file})
            if not dry_run:
                cache.delete()
                schedule_cleanup(cache.pdf_file)
    return removed


def cleanup_publication_copies(*, dry_run=True, limit=200):
    """Bounded recovery of copies whose DB transaction failed or rolled back.

    Only the new flat engine-owned namespace is eligible. Legacy project uploads
    are deliberately outside this operation, regardless of age or filename.
    """
    from .models import ElaboratoRevision
    from edilcloud.modules.projects.models import ProjectDocument

    limit = max(0, min(limit, 200))
    if not limit:
        return []
    storage = ProjectDocument._meta.get_field("document").storage
    if not isinstance(storage, FileSystemStorage):
        raise ValueError("La pulizia delle copie richiede lo storage filesystem configurato.")
    folder = "elaborati/publications"
    try:
        root = Path(getattr(storage, "publication_location", storage.location)).resolve()
        directory = Path(storage.path(folder))
    except (ImproperlyConfigured, SuspiciousFileOperation):
        raise ValueError("Directory delle copie Elaborati non valida.") from None
    if not directory.exists():
        return []
    for part in (directory.parent, directory):
        if part.is_symlink() or part.is_junction() or not part.resolve().is_relative_to(root):
            raise ValueError("Directory delle copie Elaborati non valida.")
    threshold = timezone.now() - timedelta(hours=24)
    removed = []
    for candidate in sorted(directory.iterdir()):
        match = re.fullmatch(r"([0-9a-f]{32})-[0-9a-f]{32}\.pdf", candidate.name)
        if not match or candidate.is_symlink() or not candidate.is_file():
            continue
        name = f"{folder}/{candidate.name}"
        if storage.get_modified_time(name) >= threshold:
            continue
        revision_id = uuid.UUID(hex=match[1])
        with transaction.atomic():
            locked = ElaboratoRevision.objects.select_for_update(
                skip_locked=connection.vendor == "postgresql"
            ).filter(pk=revision_id).first()
            # A skipped row is an active writer, not a missing document.
            if locked is None and ElaboratoRevision.objects.filter(pk=revision_id).exists():
                continue
            if ProjectDocument.objects.filter(document=name).exists():
                continue
            if not candidate.resolve().is_relative_to(root) or candidate.is_symlink():
                continue
            removed.append(name)
            if not dry_run:
                storage.delete(name)
            if len(removed) >= limit:
                break
    return removed

def cleanup_orphans(*, dry_run=True, limit=200):
    limit = max(0, min(limit, 200))
    if not limit:
        return []
    storage = private_document_storage()
    from .pdf_cache import referenced_files
    referenced = referenced_files()
    threshold = timezone.now() - timedelta(hours=24)
    removed = []
    for folder, extension in (("elaborati/previews", "pdf"), ("elaborati/signatures", "png")):
        try:
            _subdirectories, names = storage.listdir(folder)
        except FileNotFoundError:
            continue
        # Deliberately no recursive traversal. Only generated flat file names in
        # these two exact directories belong to this cleaner.
        for name in names:
            if not re.fullmatch(rf"[a-zA-Z0-9_-]+\.{extension}", name):
                continue
            path = f"{folder}/{name}"
            if path in referenced or storage.get_modified_time(path) >= threshold:
                continue
            removed.append(path)
            if not dry_run:
                storage.delete(path)
            if len(removed) >= limit:
                return removed
    return removed
