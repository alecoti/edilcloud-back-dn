from django.core.management.base import BaseCommand

from edilcloud.modules.projects.models import CommentAttachment, PostAttachment, ProjectDocument, ProjectModel3D, ProjectPhoto


class Command(BaseCommand):
    help = "Populate missing file sizes outside the request path, without rewriting files."

    def handle(self, *args, **options):
        updated = missing = 0
        for model in (ProjectDocument, ProjectPhoto, PostAttachment, CommentAttachment, ProjectModel3D):
            field_name = model.metadata_file_field
            rows = model.objects.filter(file_size__isnull=True).only("id", field_name).iterator(chunk_size=100)
            for row in rows:
                field = getattr(row, field_name)
                try:
                    size = field.size if field else None
                except Exception:
                    size = None
                if size is None:
                    missing += 1
                    continue
                # Do not overwrite metadata for a file replaced during the backfill.
                updated += model.objects.filter(pk=row.pk, file_size__isnull=True, **{field_name: field.name}).update(file_size=size)
        self.stdout.write(f"File sizes populated: {updated}; missing/unavailable files: {missing}")
