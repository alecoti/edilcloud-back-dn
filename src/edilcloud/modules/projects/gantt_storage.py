from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateScheduleStorage(FileSystemStorage):
    def url(self, name):
        raise ValueError("Il file originale del Gantt richiede un download autenticato.")


def project_schedule_storage():
    return PrivateScheduleStorage(location=settings.PRIVATE_STORAGE_ROOT)
