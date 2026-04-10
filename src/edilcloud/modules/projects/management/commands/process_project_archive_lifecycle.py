from django.core.management.base import BaseCommand
from django.utils import timezone

from edilcloud.modules.projects.archive import process_project_archive_lifecycle


class Command(BaseCommand):
    help = (
        "Allinea archiviazione e retention dei progetti chiusi. "
        "Elimina definitivamente solo i progetti gia pronti e solo se richiesto esplicitamente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete-ready",
            action="store_true",
            help=(
                "Elimina i progetti gia oltre la retention solo se l'export finale ai possessori "
                "risulta gia consegnato."
            ),
        )

    def handle(self, *args, **options):
        result = process_project_archive_lifecycle(
            reference_time=timezone.now(),
            delete_ready=bool(options.get("delete_ready")),
        )

        self.stdout.write(
            self.style.SUCCESS(
                (
                    "Lifecycle archiviazione completata. "
                    f"Scansionati: {result['scanned']}, "
                    f"archiviati: {result['archived']}, "
                    f"pronti per purge: {len(result['ready_to_delete_ids'])}, "
                    f"eliminati: {len(result['deleted_ids'])}."
                )
            )
        )

        if result["pending_owner_export_ids"]:
            joined_ids = ", ".join(str(project_id) for project_id in result["pending_owner_export_ids"])
            self.stdout.write(
                self.style.WARNING(
                    "Progetti oltre retention ma ancora in attesa di invio export ai possessori: "
                    f"{joined_ids}"
                )
            )
