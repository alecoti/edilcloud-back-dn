import json

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from edilcloud.modules.assistant.quality_reporting import (
    build_quality_report,
    load_project_assistant_run_logs,
)


class Command(BaseCommand):
    help = "Genera un report aggregato della qualita assistant dai run log persistiti."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200, help="Numero massimo di run assistant da analizzare.")
        parser.add_argument("--project-id", type=int, help="Filtra il report per progetto.")

    def handle(self, *args, **options):
        limit = max(int(options.get("limit") or 200), 1)
        project_id = options.get("project_id")
        close_old_connections()
        messages, error = load_project_assistant_run_logs(limit=limit, project_id=project_id)
        if error:
            self.stdout.write(json.dumps(error, ensure_ascii=True, indent=2))
            return
        report = build_quality_report(messages or [])
        self.stdout.write(json.dumps(report, ensure_ascii=True, indent=2))
