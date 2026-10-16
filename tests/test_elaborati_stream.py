import json
import uuid
from datetime import timedelta

import httpx
import pytest
from django.utils import timezone

from edilcloud.modules.elaborati.content import ReasoningResult
from edilcloud.modules.elaborati.models import DocumentAIUsage, DocumentAudit
from edilcloud.modules.elaborati.provider import DocumentProviderError, structured_response
from edilcloud.modules.elaborati.provider_stream import read_response
from tests import test_elaborati as baseline

site = baseline.site


def sse(*events):
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events).encode()


@pytest.mark.parametrize("status", ["completed", "incomplete", "failed"])
def test_stream_returns_only_terminal_response_with_usage(status):
    terminal = {"id": "response-test", "status": status, "usage": {"total_tokens": 48}}
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(
            {"type": "response.created", "response": {"id": "response-test"}},
            {"type": "response.reasoning.delta", "delta": "private reasoning"},
            {"type": "response.output_text.delta", "delta": "incomplete text"},
            {"type": "response." + status, "response": terminal},
        ),
    )
    created = []
    assert read_response(response, on_created=created.append) == terminal
    assert created == ["response-test"]


def test_stream_never_accepts_deltas_as_a_document_when_terminal_event_is_missing():
    response = httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=sse(
            {"type": "response.output_text.delta", "delta": '{"title":"half a draft"}'},
        ),
    )
    with pytest.raises(ValueError, match="evento finale"):
        read_response(response)


@pytest.mark.django_db
@pytest.mark.parametrize("terminal", [True, False])
def test_stream_integration_keeps_128k_usage_and_safe_audit_without_replaying(
    site, settings, monkeypatch, terminal
):
    settings.OPENAI_API_KEY = "test-private-key"
    revision = baseline.create(site)
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() + timedelta(minutes=8)
    job.save()
    calls = []
    payload = {
        "id": "stream-result",
        "status": "completed",
        "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
        "output": [
            {"type": "reasoning", "summary": [], "private": "private reasoning"},
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

    def reply(request):
        calls.append(json.loads(request.content))
        events = [
            {"type": "response.created", "response": {"id": payload["id"]}},
            {"type": "response.reasoning.delta", "delta": "private reasoning"},
        ]
        if terminal:
            events.append({"type": "response.completed", "response": payload})
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=sse(*events)
        )

    original = httpx.Client
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.provider.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(reply)),
    )

    def call():
        return structured_response(
            job=job,
            stage="document_reasoning",
            schema=ReasoningResult,
            instructions="test",
            data={"private": "source contents"},
        )

    if terminal:
        assert call().facts == []
        assert DocumentAIUsage.objects.get(job=job).total_tokens == 150
    else:
        with pytest.raises(DocumentProviderError, match="completato"):
            call()
        assert not DocumentAIUsage.objects.filter(job=job).exists()
        assert DocumentAudit.objects.get(revision=revision, action="ai.stream_interrupted").detail[
            "usage_unknown"
        ]
    assert len(calls) == 1 and calls[0]["stream"] is True and calls[0]["store"] is False
    assert "max_output_tokens" not in calls[0]
    audit = json.dumps(list(DocumentAudit.objects.filter(revision=revision).values("detail")))
    assert "private reasoning" not in audit and "source contents" not in audit
