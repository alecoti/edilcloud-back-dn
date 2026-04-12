from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.projects.demo_master_admin import restore_demo_master_snapshot
from edilcloud.modules.projects.management.commands.seed_rich_demo_project import (
    DEFAULT_VIEWER_EMAIL,
    DEFAULT_VIEWER_PASSWORD,
    PROJECT_BLUEPRINT,
)


class Command(BaseCommand):
    help = "Restore the Demo Master project from a specific snapshot version."

    def add_arguments(self, parser):
        parser.add_argument("--project-name", default=PROJECT_BLUEPRINT["name"])
        parser.add_argument("--snapshot-version", required=True)
        parser.add_argument("--viewer-email", default=DEFAULT_VIEWER_EMAIL)
        parser.add_argument("--viewer-password", default=DEFAULT_VIEWER_PASSWORD)

    def handle(self, *args, **options):
        project_name = options["project_name"]
        if project_name != PROJECT_BLUEPRINT["name"]:
            raise CommandError(
                f'Il restore supporta solo il Demo Master canonico "{PROJECT_BLUEPRINT["name"]}".'
            )

        try:
            result = restore_demo_master_snapshot(
                user=type("RestoreCommandUser", (), {"is_superuser": True})(),
                snapshot_version=options["snapshot_version"],
                viewer_email=options["viewer_email"],
                viewer_password=options["viewer_password"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        summary = result["restore_summary"]
        self.stdout.write(self.style.SUCCESS("Demo Master ripristinato dalla snapshot selezionata."))
        self.stdout.write(
            f'Snapshot: {summary["snapshot_version"]}\n'
            f'Task: {summary["task_count"]} | Attivita: {summary["activity_count"]}\n'
            f'Documenti: {summary["document_count"]} | Foto: {summary["photo_count"]}\n'
            f'Post: {summary["post_count"]} | Commenti: {summary["comment_count"]}\n'
            f'Asset mancanti: {summary["missing_asset_count"]}'
        )
