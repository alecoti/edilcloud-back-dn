"""Bounded cleanup of unreferenced engine artifacts, never project media."""

import re
from datetime import timedelta

from django.utils import timezone

from .storage import private_document_storage

from .models import ElaboratoRevision, PersonalSignature


def cleanup_orphans(*, dry_run=True, limit=200):
    storage = private_document_storage()
    referenced = set(
        ElaboratoRevision.objects.exclude(preview_file="").values_list("preview_file", flat=True)
    )
    referenced.update(PersonalSignature.objects.exclude(image="").values_list("image", flat=True))
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
