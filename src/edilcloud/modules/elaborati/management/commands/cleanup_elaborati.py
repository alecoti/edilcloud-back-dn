from django.core.management.base import BaseCommand
from edilcloud.modules.elaborati.maintenance import (
    cleanup_orphans, cleanup_publication_copies, cleanup_stale_display_cache,
)
import json


class Command(BaseCommand):
    help = "Elenca file temporanei Elaborati senza riferimenti e più vecchi di 24 ore; --apply per eliminarli."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        modes = parser.add_mutually_exclusive_group()
        modes.add_argument("--stale-cache", action="store_true")
        modes.add_argument("--publication-copies", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        cleanup = (cleanup_stale_display_cache if options["stale_cache"] else
                   cleanup_publication_copies if options["publication_copies"] else cleanup_orphans)
        files = cleanup(dry_run=not options["apply"])
        if options["json"]:
            self.stdout.write(json.dumps({"apply": options["apply"], "count": len(files),
                                         "entries": files}))
            return
        self.stdout.write(
            f"File {'eliminati' if options['apply'] else 'eliminabili'}: {len(files)}"
        )
