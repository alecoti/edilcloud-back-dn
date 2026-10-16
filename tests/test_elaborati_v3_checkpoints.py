from datetime import timedelta
import json

import httpx
import pytest
from django.utils import timezone

from edilcloud.modules.elaborati.checkpoints import (
    AmbiguousProviderResult, ProviderCheckpoint, StepUnavailable, run_step,
)
from edilcloud.modules.elaborati.content import ReasoningResult
from edilcloud.modules.elaborati.models import DocumentAIUsage, DocumentStep
from edilcloud.modules.elaborati.provider import structured_response
from tests import test_elaborati as baseline
from tests.test_elaborati_v3_inventory import inventory_job

site = baseline.site
pytestmark = pytest.mark.django_db


def test_completed_stage_reused_and_changed_input_rejected(site):
    job = inventory_job(site)
    calls = []

    def execute(step):
        calls.append(step.pk)
        return {"section": "Saved without repurchasing"}

    first = run_step(job=job, key="section_01", kind="write", data={"source": "v1"}, execute=execute)
    second = run_step(job=job, key="section_01", kind="write", data={"source": "v1"}, execute=execute)
    assert first == second and len(calls) == 1
    with pytest.raises(StepUnavailable, match="cambiato"):
        run_step(job=job, key="section_01", kind="write", data={"source": "v2"}, execute=execute)


def test_failed_section_resumes_without_rerunning_successful_sections(site):
    job = inventory_job(site)
    calls = []

    def section(number):
        def execute(step):
            calls.append(number)
            if number == 3 and calls.count(3) == 1:
                raise ValueError("Recoverable local processing failure")
            return {"number": number}
        return run_step(job=job, key=f"section_{number}", kind="write", data={"n": number}, execute=execute)

    section(1)
    section(2)
    with pytest.raises(ValueError):
        section(3)
    for number in (1, 2, 3):
        assert section(number) == {"number": number}
    assert calls == [1, 2, 3, 3]


def test_sent_ambiguous_call_cannot_automatically_restart(site):
    job = inventory_job(site)
    count = []

    def execute(step):
        count.append(1)
        checkpoint = ProviderCheckpoint(job, stage="read", model="gpt-6-luna", effort="high")
        checkpoint.sent()
        checkpoint.created("response-pending")
        raise httpx.ReadTimeout("Ambiguous disconnect")

    with pytest.raises(httpx.ReadTimeout):
        run_step(job=job, key="read_1", kind="read", data={}, execute=execute)
    step = job.steps.get()
    assert step.state == "unknown" and step.attempts.get().response_id == "response-pending"
    with pytest.raises(AmbiguousProviderResult):
        run_step(job=job, key="read_1", kind="read", data={}, execute=execute)
    assert len(count) == 1


def test_provider_response_saved_before_local_crash_and_ledger_remains_once(site, settings, monkeypatch):
    job = inventory_job(site)
    settings.OPENAI_API_KEY = "not-a-real-key"
    calls = []
    body = {"facts": [], "duplicates": [], "contradictions": [], "missing_data": []}
    payload = {"id": "v3-checkpoint-response", "status": "completed",
               "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
               "output": [{"type": "reasoning", "content": [{"type": "reasoning_text", "text": "PRIVATE"}]},
                          {"type": "message", "content": [{"type": "output_text", "text": json.dumps(body)}]}]}

    def reply(request):
        calls.append(1)
        return httpx.Response(200, json=payload)

    original = httpx.Client
    monkeypatch.setattr("edilcloud.modules.elaborati.provider.httpx.Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(reply)))
    local_runs = []

    def execute(step):
        value = structured_response(job=job, stage="document_reasoning", schema=ReasoningResult,
                                    instructions="QA", data={})
        local_runs.append(1)
        if len(local_runs) == 1:
            raise ValueError("Crash after provider completion")
        return value

    for expected_failure in (True, False):
        if expected_failure:
            with pytest.raises(ValueError):
                run_step(job=job, key="reasoning", kind="reasoning", data={}, execute=execute, schema=ReasoningResult)
        else:
            result = run_step(job=job, key="reasoning", kind="reasoning", data={}, execute=execute, schema=ReasoningResult)
            assert result.facts == []
    assert len(calls) == 1 and DocumentAIUsage.objects.get(job=job).total_tokens == 30
    attempt = job.steps.get().attempts.get()
    assert attempt.model == "gpt-6-luna" and attempt.effort == "high"
    assert "PRIVATE" not in json.dumps(attempt.response)
    assert attempt.usage["total_tokens"] == 30


def test_stale_worker_or_corrupt_output_cannot_be_reused(site):
    job = inventory_job(site)
    run_step(job=job, key="local", kind="local", data={}, execute=lambda step: {"ok": True})
    DocumentStep.objects.filter(job=job).update(output={"ok": False})
    with pytest.raises(StepUnavailable, match="Integrità"):
        run_step(job=job, key="local", kind="local", data={}, execute=lambda step: {})
    type(job).objects.filter(pk=job.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(StepUnavailable, match="prenotazione"):
        run_step(job=job, key="new", kind="local", data={}, execute=lambda step: {})


@pytest.mark.parametrize("state", ["sent", "unknown", "completed"])
def test_finite_budget_holds_reservation_until_ledger_including_terminal_checkpoint(site, settings, monkeypatch, state):
    from edilcloud.modules.elaborati.checkpoints import step_context

    job = inventory_job(site)
    job.workflow_version = "v3.1"
    job.reserved_tokens = 0
    job.save()
    settings.AI_TOKEN_QUOTA_ENFORCED = True
    monkeypatch.setattr("edilcloud.modules.billing.services.ai_quota_is_unlimited", lambda account: False)
    monkeypatch.setattr("edilcloud.modules.billing.services.entitlement_snapshot",
                        lambda account: {"ai_tokens": {"remaining_this_period": 150000}})
    step = DocumentStep.objects.create(job=job, key="paid", kind="write", input_hash="x")
    step.attempts.create(number=1, input_hash="x", model="gpt-6-luna", state=state, reserved_tokens=128000)

    def execute(current):
        ProviderCheckpoint(job, stage="write", model="gpt-6-luna", effort="medium").sent(reservation=128000)
        return {}

    with pytest.raises(StepUnavailable, match="Budget insufficiente"):
        run_step(job=job, key="next", kind="write", data={}, execute=execute)
    # Accounting clears this reservation in the same transaction as usage.
    step.attempts.update(reserved_tokens=0)
    current = job.steps.get(key="next")
    current.state = "running"
    current.save()
    with step_context(current):
        checkpoint = ProviderCheckpoint(job, stage="write", model="gpt-6-luna", effort="medium")
        checkpoint.sent(reservation=128000)
        assert checkpoint.attempt.reserved_tokens == 128000


def test_step_summaries_survive_local_pdf_job_and_remain_private(site):
    import uuid
    from edilcloud.modules.elaborati import services
    from edilcloud.modules.elaborati.models import DocumentJob

    job = inventory_job(site)
    job.workflow_version = "v3.1"
    job.state = "completed"
    job.save()
    summary = {"id": "qa-public", "stage": "document_factual", "status": "completed",
               "parts": [{"text": "Confronto le fonti originali.", "complete": True}]}
    job.steps.create(key="review", kind="review", input_hash="x", thinking=[summary])
    DocumentJob.objects.create(revision=job.revision, requested_by=job.requested_by, action="preview",
                               state="completed", idempotency_key=uuid.uuid4(), input_version=job.input_version)
    own = services.serialize_revision(job.revision, full=True, viewer_user_id=job.requested_by.user_id)
    assert own["thinking"] == [summary]
    assert services.serialize_revision(job.revision, full=True, viewer_user_id=site[2].user_id)["thinking"] == []
