from pathlib import Path
from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateDocumentStorage(FileSystemStorage):
    # Resolve this custom setting on access, including when overridden in tests.
    @property
    def base_location(self):
        return str(settings.PRIVATE_STORAGE_ROOT)

    @property
    def location(self):
        return str(Path(self.base_location).resolve())

    def url(self, name):
        raise ValueError("L'artefatto Elaborati richiede un download autenticato.")


def private_document_storage():
    return PrivateDocumentStorage()
