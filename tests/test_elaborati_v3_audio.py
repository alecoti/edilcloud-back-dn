"""Audio quota/ledger recovery: no paid result silently lost or repurchased."""
import io
import wave

import httpx
import pytest

from edilcloud.modules.elaborati.checkpoints import run_step
from edilcloud.modules.elaborati.intelligence_media import transcribe_segment, transcription_reservation
from edilcloud.modules.elaborati.models import DocumentAIUsage
from edilcloud.modules.elaborati.provider import DocumentProviderError
from tests import test_elaborati as baseline
from tests.test_elaborati_v3_inventory import inventory_job

site = baseline.site
pytestmark = pytest.mark.django_db


def wav(seconds=2):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000 * seconds)
    return output.getvalue()


def finite_audio(site, settings, monkeypatch, *, text="Verifica conclusa alle ore quattordici."):
    job = inventory_job(site)
    job.workflow_version = "v3.2"
    job.reserved_tokens = 0
    job.save()
    settings.AI_TOKEN_QUOTA_ENFORCED = True
    settings.OPENAI_API_KEY = "synthetic-audio-test-key"
    monkeypatch.setattr("edilcloud.modules.billing.services.ai_quota_is_unlimited", lambda account: False)
    monkeypatch.setattr("edilcloud.modules.billing.services.entitlement_snapshot",
                        lambda account: {"ai_tokens": {"remaining_this_period": 50000}})
    calls = []

    def reply(*args, **kwargs):
        calls.append(1)
        attempt = job.steps.get(key="audio:one").attempts.get()
        assert attempt.state == "sent" and attempt.reserved_tokens == transcription_reservation(wav())
        assert "max_output_tokens" not in kwargs["data"]
        return httpx.Response(200, headers={"x-request-id": "audio-qa-one"}, json={
            "text": text, "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70}})

    monkeypatch.setattr("edilcloud.modules.elaborati.intelligence_media.httpx.post", reply)
    return job, calls


def execute(job):
    return run_step(job=job, key="audio:one", kind="document_transcription", data={"sha": "one"},
                    execute=lambda step: transcribe_segment(job, wav(), "segment.wav"))


def test_finite_audio_quota_is_reserved_released_and_not_rebilled(site, settings, monkeypatch):
    job, calls = finite_audio(site, settings, monkeypatch)
    first = execute(job)
    assert first["text"] == "Verifica conclusa alle ore quattordici."
    assert first["human_verified"] is False
    assert execute(job) == first and calls == [1]
    assert DocumentAIUsage.objects.get(job=job).total_tokens == 70
    job.refresh_from_db()
    assert job.consumed_tokens == 70
    assert job.steps.get().attempts.get().reserved_tokens == 0


def test_empty_paid_transcription_is_accounted_and_rejected_without_new_http(site, settings, monkeypatch):
    job, calls = finite_audio(site, settings, monkeypatch, text="")
    for _ in range(2):
        with pytest.raises(DocumentProviderError, match="vuoto"):
            execute(job)
    assert calls == [1] and DocumentAIUsage.objects.get(job=job).total_tokens == 70
    assert job.steps.get().attempts.get().reserved_tokens == 0
    assert job.steps.get().state == "failed"


def test_audio_crash_between_checkpoint_and_ledger_recovers_without_repurchase(site, settings, monkeypatch):
    job, calls = finite_audio(site, settings, monkeypatch)
    billing_calls = []

    def billing(**kwargs):
        billing_calls.append(1)
        if len(billing_calls) == 1:
            raise RuntimeError("Synthetic crash before ledger commit")

    monkeypatch.setattr("edilcloud.modules.billing.services.apply_ai_usage_to_billing", billing)
    with pytest.raises(RuntimeError, match="Synthetic crash"):
        execute(job)
    assert not DocumentAIUsage.objects.filter(job=job).exists()
    attempt = job.steps.get().attempts.get()
    assert attempt.state == "completed" and attempt.reserved_tokens > 0
    assert execute(job)["text"] and calls == [1]
    assert DocumentAIUsage.objects.get(job=job).total_tokens == 70
    attempt.refresh_from_db()
    assert attempt.reserved_tokens == 0


def test_audio_reservation_uses_duration_and_rejects_invalid_bytes():
    assert transcription_reservation(wav(120)) > transcription_reservation(wav(2)) > 0
    with pytest.raises(DocumentProviderError, match="non valido"):
        transcription_reservation(b"not audio")
