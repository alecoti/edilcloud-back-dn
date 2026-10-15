import json
import uuid
from datetime import timedelta

import httpx
import pytest
from django.core.management import call_command
from django.utils import timezone

from edilcloud.modules.billing.models import BillingTokenLedger
from edilcloud.modules.billing.services import (
    ai_quota_is_unlimited,
    assert_ai_request_headroom,
    entitlement_snapshot,
    get_workspace_billing_account,
)
from edilcloud.modules.elaborati.content import ReasoningResult
from edilcloud.modules.elaborati.models import DocumentAIUsage
from edilcloud.modules.elaborati.provider import structured_response
from tests.test_elaborati import create
from tests import test_elaborati

site = test_elaborati.site

pytestmark = pytest.mark.django_db


def test_unlimited_is_scoped_to_billing_owner_and_other_accounts_stay_limited(site, settings):
    settings.AI_TOKEN_QUOTA_ENFORCED = True
    account = get_workspace_billing_account(site[0].workspace)
    account.monthly_ai_tokens_base = 0
    account.metadata = {"ai_quota_unlimited": True}
    account.save()
    assert_ai_request_headroom(site[0].workspace, minimum_headroom=1_000_000)
    assert entitlement_snapshot(account)["ai_tokens"]["unlimited"] is True
    assert create(site).jobs.get().state == "queued"

    other = get_workspace_billing_account(site[3].workspace)
    other.monthly_ai_tokens_base = 0
    other.save()
    assert not ai_quota_is_unlimited(other)
    with pytest.raises(ValueError, match="Token AI insufficienti"):
        assert_ai_request_headroom(site[3].workspace)


def test_override_requires_real_boolean_and_management_command_is_audited_and_reversible(site, settings):
    settings.AI_TOKEN_QUOTA_ENFORCED = True
    account = get_workspace_billing_account(site[0].workspace)
    account.metadata = {"ai_quota_unlimited": "true", "other_setting": "preserved"}
    account.save()
    assert not ai_quota_is_unlimited(account)
    args = (
        "set_account_ai_quota",
        "--owner-user-id",
        str(account.owner_user_id),
        "--reason",
        "Explicit owner request",
    )
    call_command(*args, "--unlimited", "--dry-run")
    account.refresh_from_db()
    assert not ai_quota_is_unlimited(account)
    call_command(*args, "--unlimited")
    account.refresh_from_db()
    assert ai_quota_is_unlimited(account)
    assert account.metadata["other_setting"] == "preserved"
    assert account.metadata["ai_quota_audit"][-1]["reason"] == "Explicit owner request"
    call_command(*args, "--limited")
    account.refresh_from_db()
    assert not ai_quota_is_unlimited(account)


@pytest.mark.parametrize("global_unlimited", [False, True])
def test_unlimited_elaborato_keeps_real_usage_without_per_job_budget_rejection_or_credit_debit(
    site, settings, monkeypatch, global_unlimited
):
    settings.AI_TOKEN_QUOTA_ENFORCED = not global_unlimited
    settings.OPENAI_API_KEY = "synthetic-not-a-real-key"
    settings.OPENAI_API_BASE_URL = "https://openai.example/v1"
    account = get_workspace_billing_account(site[0].workspace)
    account.metadata = {} if global_unlimited else {"ai_quota_unlimited": True}
    account.monthly_ai_tokens_base = 0
    account.ai_token_balance_topup = 75
    account.save()
    revision = create(site)
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() + timedelta(minutes=8)
    job.save()
    paths = []
    original = httpx.Client

    def reply(request):
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "id": "resp-unlimited-test",
                "status": "completed",
                "usage": {"input_tokens": 490000, "output_tokens": 10000, "total_tokens": 500000},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "facts": [],
                                        "duplicates": [],
                                        "contradictions": [],
                                        "missing_data": [],
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(
        "edilcloud.modules.elaborati.provider.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(reply)),
    )
    structured_response(
        job=job,
        stage="test",
        schema=ReasoningResult,
        instructions="test",
        data={"large": "a" * 100000},
    )
    assert paths == ["/v1/responses"]
    assert DocumentAIUsage.objects.get(job=job).total_tokens == 500000
    account.refresh_from_db()
    assert account.ai_token_balance_topup == 75
    assert not BillingTokenLedger.objects.filter(billing_account=account).exists()


def test_global_disabled_quota_covers_existing_and_new_accounts_and_job_reservations(site, settings):
    settings.AI_TOKEN_QUOTA_ENFORCED = False
    for workspace in (site[0].workspace, site[3].workspace):
        account = get_workspace_billing_account(workspace)
        account.monthly_ai_tokens_base = 0
        account.metadata = {"ai_quota_unlimited": False}
        account.save()
        assert ai_quota_is_unlimited(account)
        assert_ai_request_headroom(workspace, minimum_headroom=10**12)
        assert entitlement_snapshot(account)["ai_tokens"]["unlimited"] is True

    # The second job must not be blocked by the first job's token reservation.
    assert create(site).jobs.get().state == "queued"
    assert create(site).jobs.get().state == "queued"
    # Re-enabling quotas works without undoing per-account metadata changes.
    settings.AI_TOKEN_QUOTA_ENFORCED = True
    account.refresh_from_db()
    assert not ai_quota_is_unlimited(account)
    with pytest.raises(ValueError, match="Token AI insufficienti"):
        assert_ai_request_headroom(site[3].workspace)
