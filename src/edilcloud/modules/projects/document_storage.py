"""Project uploads keep their storage; issued Elaborati copies are private.

Logical names remain stable. A separate migration/retirement command must move
existing public copies before rollout; this adapter never falls back to media.
"""

import re
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation

from edilcloud.modules.elaborati.storage import PrivateDocumentStorage
from edilcloud.modules.files.image_storage import OptimizedImageStorage

PUBLICATION_FOLDER = "elaborati/publications"


def is_publication_name(name):
    return name == PUBLICATION_FOLDER or name.startswith(PUBLICATION_FOLDER + "/")


def publication_revision(name):
    match = re.fullmatch(r"elaborati/publications/([0-9a-f]{32})-[a-zA-Z0-9_-]+\.pdf", name)
    return UUID(hex=match[1]) if match else None


class PublicationStorage(PrivateDocumentStorage):
    def path(self, name):
        root = Path(self.location).resolve()
        media = Path(settings.MEDIA_ROOT).resolve()
        target = Path(super().path(name))
        if root.is_relative_to(media) or target.resolve().is_relative_to(media):
            raise ImproperlyConfigured(
                "Lo storage Elaborati deve restare fuori dai media pubblici."
            )
        if not target.resolve().is_relative_to(root):
            raise SuspiciousFileOperation("Percorso della pubblicazione non valido.")
        current = root
        for part in target.relative_to(root).parts:
            current /= part
            if current.is_symlink() or current.is_junction():
                raise SuspiciousFileOperation("Link non ammesso nello storage delle pubblicazioni.")
        return str(target)


class ProjectDocumentStorage(OptimizedImageStorage):
    @property
    def publication_location(self):
        storage = PublicationStorage()
        # Validate disjoint roots even when no publication has been written yet.
        storage.path(PUBLICATION_FOLDER)
        return storage.location

    def path(self, name):
        if is_publication_name(name):
            return PublicationStorage().path(name)
        return super().path(name)

    def _save(self, name, content):
        if is_publication_name(name):
            return PublicationStorage()._save(name, content)
        return super()._save(name, content)

    def url(self, name):
        if is_publication_name(name):
            revision = publication_revision(name)
            if revision is None:
                raise ValueError("La pubblicazione richiede un riferimento valido.")
            return f"/api/v1/elaborati/revisions/{revision}/pdf"
        return super().url(name)


def project_document_storage():
    return ProjectDocumentStorage()
