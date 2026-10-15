from django.core.management.base import BaseCommand
from edilcloud.modules.elaborati.maintenance import cleanup_orphans


class Command(BaseCommand):
    help = "Elenca file temporanei Elaborati senza riferimenti e più vecchi di 24 ore; --apply per eliminarli."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        files = cleanup_orphans(dry_run=not options["apply"])
        self.stdout.write(
            f"File {'eliminati' if options['apply'] else 'eliminabili'}: {len(files)}"
        )
