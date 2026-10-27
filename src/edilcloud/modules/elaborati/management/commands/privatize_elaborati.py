import json
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from edilcloud.modules.elaborati.privatization import transfer_batch


class Command(BaseCommand):
    help = "Anteprima del trasferimento delle copie PDF nel privato; --apply --maintenance per applicare."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--maintenance", action="store_true")
        parser.add_argument("--revision", type=UUID)
        parser.add_argument("--after", type=UUID)
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        if options["apply"] and not options["maintenance"]:
            raise CommandError("Arrestare API/worker e indicare --maintenance prima di --apply.")
        if not 1 <= options["limit"] <= 200:
            raise CommandError("--limit deve essere compreso tra 1 e 200.")
        entries = transfer_batch(
            apply=options["apply"],
            maintenance=options["maintenance"],
            revision_id=options["revision"],
            after=options["after"],
            limit=options["limit"],
        )
        self.stdout.write(
            json.dumps({"apply": options["apply"], "count": len(entries), "entries": entries})
        )
        if any(entry["status"] in ("blocked", "retirement_pending") for entry in entries):
            raise CommandError(
                "Trasferimento incompleto; consultare gli esiti e riprendere dopo la correzione."
            )
