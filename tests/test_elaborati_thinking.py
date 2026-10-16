import json
import uuid
from datetime import timedelta

import httpx
import pytest
from django.test import Client
from django.utils import timezone

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.content import ReasoningResult
from edilcloud.modules.elaborati.models import DocumentAIUsage
from edilcloud.modules.elaborati.provider import structured_response, DocumentProviderError
from edilcloud.modules.elaborati.provider_stream import read_response
from edilcloud.modules.elaborati.thinking import ReasoningProgress
from tests import test_elaborati as baseline
from tests.test_elaborati_stream import sse
from tests.test_notifications_api import auth_header, login_and_get_token

site = baseline.site


def test_summary_stream_accepts_only_public_parts_and_does_not_duplicate_final_text():
    item = {
        "type": "reasoning",
        "content": [{"type": "reasoning_text", "text": "PRIVATE"}],
        "summary": [{"type": "summary_text", "text": "Confronto le date delle fonti."}],
    }
    payload = {"id": "summary-test", "status": "completed", "output": [item]}
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(
            {
                "type": "response.reasoning_text.delta",
                "output_index": 0,
                "content_index": 0,
                "delta": "PRIVATE",
            },
            {"type": "response.output_text.delta", "delta": "PRIVATE DOCUMENT JSON"},
            {
                "type": "response.reasoning_summary_text.delta",
                "output_index": 0,
                "summary_index": 0,
                "delta": "Confronto ",
            },
            {
                "type": "response.reasoning_summary_text.delta",
                "output_index": 0,
                "summary_index": 0,
                "delta": "le date delle fonti.",
            },
            {
                "type": "response.reasoning_summary_text.done",
                "output_index": 0,
                "summary_index": 0,
                "text": "Confronto le date delle fonti.",
            },
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": payload},
        ),
    )
    parts = {}

    def summary(out, index, text, *, append, complete):
        key = (out, index)
        parts[key] = parts.get(key, "") + text if append else text

    assert read_response(response, on_summary=summary) == payload
    assert parts == {(0, 0): "Confronto le date delle fonti."}
    assert "PRIVATE" not in str(parts)


def running_job(site):
    revision = baseline.create(site)
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() + timedelta(minutes=8)
    job.save()
    return job


@pytest.mark.django_db
def test_progress_is_live_fenced_retained_and_private_to_requester(site):
    job = running_job(site)
    progress = ReasoningProgress(job, "document_reasoning")
    progress.summary(0, 0, "Confronto le fonti", append=True)
    progress.flush(force=True)
    job.refresh_from_db()
    assert (
        services.serialize_job(job, include_thinking=True)["thinking"][0]["parts"][0]["text"]
        == "Confronto le fonti"
    )
    assert services.serialize_job(job)["thinking"] == []
    progress.finish("completed")
    job.refresh_from_db()
    assert job.thinking[0]["status"] == "completed"
    # A second model pass retains the first pass's public summary.
    second = ReasoningProgress(job, "document_composition")
    second.summary(0, 0, "Preparo il registro delle lavorazioni.", complete=True)
    second.finish("completed")
    job.refresh_from_db()
    assert len(job.thinking) == 2
    client = Client()
    owner_token = login_and_get_token(email=site[1].user.email, password="test123")
    own = client.get(f"/api/v1/elaborati/jobs/{job.pk}", **auth_header(owner_token))
    assert len(own.json()["thinking"]) == 2
    # A published document does not expose its author's AI summaries to readers.
    revision = job.revision
    revision.state = "published"
    revision.save()
    worker_token = login_and_get_token(email=site[2].user.email, password="test123")
    other = client.get(f"/api/v1/elaborati/jobs/{job.pk}", **auth_header(worker_token))
    assert other.status_code == 200 and other.json()["thinking"] == []
    # A stale worker may not replace progress after another worker took over.
    type(job).objects.filter(pk=job.pk).update(lease_token=uuid.uuid4())
    second.summary(0, 0, "STALE", complete=True)
    job.refresh_from_db()
    assert "STALE" not in json.dumps(job.thinking)


@pytest.mark.django_db
@pytest.mark.parametrize("reject_summary", [False, True])
def test_provider_requests_summaries_in_existing_call_and_safe_rejection_fallback(
    site, settings, monkeypatch, reject_summary
):
    settings.OPENAI_API_KEY = "test-not-a-real-key"
    job = running_job(site)
    payload = {
        "id": "summary-response",
        "status": "completed",
        "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        "output": [
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "Verifico le date."}],
                "private": "PRIVATE",
            },
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
            },
        ],
    }
    calls = []

    def reply(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1 and reject_summary:
            return httpx.Response(
                400, json={"error": {"param": "reasoning.summary", "code": "unsupported_parameter"}}
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(
                {"type": "response.created", "response": {"id": payload["id"]}},
                {"type": "response.reasoning_text.delta", "delta": "PRIVATE"},
                {
                    "type": "response.reasoning_summary_text.delta",
                    "output_index": 0,
                    "summary_index": 0,
                    "delta": "Verifico le date.",
                },
                {"type": "response.completed", "response": payload},
            ),
        )

    original = httpx.Client
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.provider.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(reply)),
    )
    result = structured_response(
        job=job, stage="document_reasoning", schema=ReasoningResult, instructions="test", data={}
    )
    assert result.facts == [] and calls[0]["reasoning"]["summary"] == "auto"
    assert "max_output_tokens" not in calls[0]
    assert len(calls) == (2 if reject_summary else 1)
    if reject_summary:
        assert "summary" not in calls[1]["reasoning"]
    assert DocumentAIUsage.objects.get(job=job).total_tokens == 30
    job.refresh_from_db()
    assert job.thinking[0]["parts"][0]["text"] == "Verifico le date."
    assert "PRIVATE" not in json.dumps(job.thinking)


@pytest.mark.django_db
@pytest.mark.parametrize("error", [{"param": "input", "code": "invalid_request_error"}, "unavailable"])
def test_unsupported_summary_fallback_never_replays_generic_provider_failures(
    site, settings, monkeypatch, error
):
    settings.OPENAI_API_KEY = "test-not-a-real-key"
    job = running_job(site)
    calls = []

    def reply(request):
        calls.append(request)
        return httpx.Response(400, json={"error": error})

    original = httpx.Client
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.provider.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(reply)),
    )
    with pytest.raises(DocumentProviderError):
        structured_response(
            job=job,
            stage="document_reasoning",
            schema=ReasoningResult,
            instructions="test",
            data={},
        )
    assert len(calls) == 1 and not DocumentAIUsage.objects.filter(job=job).exists()
