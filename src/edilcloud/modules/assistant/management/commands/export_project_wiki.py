from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.assistant.wiki_service import export_project_wiki_markdown
from edilcloud.modules.projects.models import Project


class Command(BaseCommand):
    help = "Esporta la wiki DB primaria dell'assistant in Markdown per audit e review."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, help="Esporta solo il progetto specificato.")
        parser.add_argument("--all", action="store_true", help="Esporta tutte le wiki progetto.")
        parser.add_argument("--output-dir", type=str, help="Cartella base di export Markdown.")
        parser.add_argument("--rebuild", action="store_true", help="Ricompila la wiki prima dell'export.")

    def handle(self, *args, **options):
        project_id = options.get("project_id")
        export_all = bool(options.get("all"))
        output_dir = options.get("output_dir")
        rebuild = bool(options.get("rebuild"))

        if not project_id and not export_all:
            raise CommandError("Specifica --project-id oppure --all.")

        queryset = Project.objects.select_related("workspace").order_by("id")
        if project_id:
            queryset = queryset.filter(id=project_id)
        projects = list(queryset)
        if project_id and not projects:
            raise CommandError(f"Progetto #{project_id} non trovato.")

        written_count = 0
        for project in projects:
            paths = export_project_wiki_markdown(
                project,
                output_dir=Path(output_dir) if output_dir else None,
                rebuild=rebuild,
            )
            written_count += len(paths)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Wiki progetto #{project.id} esportata: {len(paths)} file in {paths[0].parent}"
                )
            )

        self.stdout.write(self.style.SUCCESS(f"Export completato: {written_count} file Markdown."))
