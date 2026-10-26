import time
import logging

from django.core.management.base import BaseCommand

from edilcloud.modules.elaborati.jobs import process_batch


class Command(BaseCommand):
    help = "Elabora la coda durevole di redazione e anteprima degli elaborati."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=float, default=2)

    def handle(self, *args, **options):
        last_cleanup = 0.0
        while True:
            if time.monotonic() - last_cleanup > 3600:
                from edilcloud.modules.elaborati.maintenance import (
                    cleanup_orphans, cleanup_publication_copies, cleanup_stale_display_cache,
                )

                try:
                    cleanup_stale_display_cache(dry_run=False)
                    cleanup_publication_copies(dry_run=False)
                    cleanup_orphans(dry_run=False)
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Elaborati maintenance deferred; queue processing continues", exc_info=True
                    )
                last_cleanup = time.monotonic()
            processed = process_batch()
            if options["once"]:
                self.stdout.write(f"Elaborazioni eseguite: {processed}")
                return
            if not processed:
                time.sleep(max(0.5, options["interval"]))
