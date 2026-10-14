import json

from django.core.management.base import BaseCommand

from edilcloud.modules.projects.weather import refresh_active_project_weather


class Command(BaseCommand):
    help = "Refresh current weather (3h) and daily forecasts for recently active sites."

    def add_arguments(self, parser):
        parser.add_argument("--active-days", type=int, default=7)

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(refresh_active_project_weather(active_days=max(1, options["active_days"]))))
