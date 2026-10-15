import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from edilcloud.modules.notifications.outbox import due_push_jobs, process_push_job


class Command(BaseCommand):
    help = "Process persistent push jobs, recovering retries and expired worker leases."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=10)
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            processed = sum(process_push_job(item) for item in list(due_push_jobs(limit=max(1, options["limit"]))))
            if options["once"]:
                self.stdout.write(str(processed))
                return
            time.sleep(max(1, options["interval"]))
