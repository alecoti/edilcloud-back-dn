from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.projects.demo_master_admin import reset_demo_master_project
from edilcloud.modules.projects.management.commands.seed_rich_demo_project import (
    DEFAULT_VIEWER_EMAIL,
    DEFAULT_VIEWER_PASSWORD,
    PROJECT_BLUEPRINT,
)


class Command(BaseCommand):
    help = "Reset the Demo Master project to the current canonical seed."

    def add_arguments(self, parser):
        parser.add_argument("--project-name", default=PROJECT_BLUEPRINT["name"])
        parser.add_argument("--viewer-email", default=DEFAULT_VIEWER_EMAIL)
        parser.add_argument("--viewer-password", default=DEFAULT_VIEWER_PASSWORD)
        parser.add_argument("--skip-active-snapshot-link", action="store_true")

    def handle(self, *args, **options):
        project_name = options["project_name"]
        if project_name != PROJECT_BLUEPRINT["name"]:
            raise CommandError(
                f'Il reset seed corrente supporta solo il Demo Master canonico "{PROJECT_BLUEPRINT["name"]}".'
            )
        try:
            result = reset_demo_master_project(
                user=type("ResetCommandUser", (), {"is_superuser": True})(),
                viewer_email=options["viewer_email"],
                viewer_password=options["viewer_password"],
                skip_active_snapshot_link=options["skip_active_snapshot_link"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        summary = result["reset_summary"]
        self.stdout.write(self.style.SUCCESS("Demo Master ripristinato dal seed canonico."))
        self.stdout.write(
            f'Project #{summary["project_id"]}: {summary["project_name"]}\n'
            f'Avanzamento: {summary["progress_percentage"]}%\n'
            f'Documenti: {summary["documents"]} | Foto: {summary["photos"]}\n'
            f'Post: {summary["posts"]} | Commenti: {summary["comments"]}\n'
            f'Snapshot attivo riagganciato: {summary["reattached_snapshot_version"] or "-"}'
        )
