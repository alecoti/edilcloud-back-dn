import json
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from edilcloud.modules.billing.models import BillingAccount


class Command(BaseCommand):
    help = "Grant or revoke an administrative AI quota exemption for one billing owner."

    def add_arguments(self, parser):
        parser.add_argument("--owner-user-id", type=int, required=True)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--unlimited", action="store_true")
        mode.add_argument("--limited", action="store_true")
        parser.add_argument("--reason", required=True)
        parser.add_argument("--dry-run", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        account = (
            BillingAccount.objects.select_for_update()
            .filter(owner_user_id=options["owner_user_id"])
            .first()
        )
        if not account:
            raise CommandError("Billing account not found; no changes made.")
        if not options["reason"].strip():
            raise CommandError("A reason is required.")
        unlimited = options["unlimited"]
        previous = account.metadata.get("ai_quota_unlimited") is True
        if not options["dry_run"]:
            metadata = dict(account.metadata)
            history = list(metadata.get("ai_quota_audit", []))[-49:]
            history.append(
                {
                    "at": timezone.now().isoformat(),
                    "previous": previous,
                    "unlimited": unlimited,
                    "reason": options["reason"][:500],
                }
            )
            account.metadata = {
                **metadata,
                "ai_quota_unlimited": unlimited,
                "ai_quota_audit": history,
            }
            account.save(update_fields=("metadata", "updated_at"))
        self.stdout.write(
            json.dumps(
                {
                    "account_id": account.pk,
                    "owner_user_id": account.owner_user_id,
                    "unlimited": unlimited,
                    "previous": previous,
                    "dry_run": options["dry_run"],
                }
            )
        )
