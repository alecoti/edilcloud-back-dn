from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from edilcloud.modules.projects.demo_master_admin import create_demo_master_snapshot
from edilcloud.modules.projects.management.commands.seed_rich_demo_project import PROJECT_BLUEPRINT
from edilcloud.modules.workspaces.models import Profile


class Command(BaseCommand):
    help = "Create or update a versioned freeze point for the Demo Master project."

    def add_arguments(self, parser):
        parser.add_argument("--project-name", default=PROJECT_BLUEPRINT["name"])
        parser.add_argument("--snapshot-version")
        parser.add_argument("--business-date")
        parser.add_argument("--notes", default="")
        parser.add_argument("--created-by-email")
        parser.add_argument("--validate", action="store_true")
        parser.add_argument("--activate", action="store_true")
        parser.add_argument("--write-json", action="store_true", default=False)

    def handle(self, *args, **options):
        project_name = options["project_name"]
        if project_name != PROJECT_BLUEPRINT["name"]:
            raise CommandError(
                f'Il freeze point supporta solo il Demo Master canonico "{PROJECT_BLUEPRINT["name"]}".'
            )

        created_by = None
        if options.get("created_by_email"):
            created_by = (
                Profile.objects.select_related("workspace")
                .filter(email__iexact=options["created_by_email"], is_active=True)
                .order_by("id")
                .first()
            )
            if created_by is None:
                raise CommandError(f'Profilo con email "{options["created_by_email"]}" non trovato.')

        command_user = type("SnapshotCommandUser", (), {"is_superuser": True})()
        try:
            result = create_demo_master_snapshot(
                user=command_user,
                created_by_profile=created_by,
                snapshot_version=options["snapshot_version"],
                business_date=(
                    timezone.datetime.fromisoformat(options["business_date"]).date()
                    if options.get("business_date")
                    else None
                ),
                notes=options["notes"],
                validate=options["validate"],
                activate=options["activate"],
                write_json=options["write_json"],
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        snapshot = result["active_snapshot"] if options["activate"] else None
        if snapshot is None:
            snapshot = next(
                (
                    item
                    for item in result["recent_snapshots"]
                    if item and item.get("version") == (options["snapshot_version"] or "")
                ),
                None,
            )
        if snapshot is None:
            snapshot = result["recent_snapshots"][0] if result["recent_snapshots"] else None

        self.stdout.write(self.style.SUCCESS("Demo Master snapshot salvato."))
        if snapshot is not None:
            self.stdout.write(
                f'Project: {result["canonical_project_name"]}\n'
                f'Snapshot #{snapshot["id"]}: {snapshot["version"]}\n'
                f'Business date: {snapshot["business_date"]}\n'
                f'Schema version: {snapshot["schema_version"]}\n'
                f'Seed hash: {snapshot["seed_hash"]}\n'
                f'Asset manifest hash: {snapshot["asset_manifest_hash"]}\n'
                f'Payload hash: {snapshot["payload_hash"]}\n'
                f'Validation: {snapshot["validation_status"]}\n'
                f'Active in production: {"yes" if snapshot["active_in_production"] else "no"}\n'
                f'Export: {snapshot["export_relative_path"] or "-"}'
            )
        else:
            self.stdout.write(result["detail"])
