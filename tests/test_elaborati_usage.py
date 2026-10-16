import uuid

import pytest
from django.test import Client

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.models import DocumentAIUsage, DocumentAudit, DocumentJob
from edilcloud.modules.elaborati.usage import document_token_usage
from tests import test_elaborati as baseline
from tests.test_notifications_api import auth_header, login_and_get_token

site = baseline.site
pytestmark = pytest.mark.django_db


def record(job, *, input_tokens, output_tokens):
    return DocumentAIUsage.objects.create(
        job=job,
        workspace=job.revision.elaborato.project.workspace,
        stage="document_composition",
        response_id=str(uuid.uuid4()),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


def test_usage_is_document_wide_including_failed_calls_and_does_not_double_count_thinking(site):
    revision = baseline.create(site)
    first_job = revision.jobs.get()
    first_job.state = "failed"
    first_job.save()
    record(first_job, input_tokens=100, output_tokens=50)
    DocumentAudit.objects.create(
        revision=revision,
        action="ai.response",
        detail={"reasoning_tokens": 30, "cached_input_tokens": 40},
    )
    revision.state = "published"
    revision.save()
    second_revision = services.new_revision(profile=site[1], revision_id=revision.pk)
    second_job = DocumentJob.objects.create(
        revision=second_revision,
        requested_by=site[1],
        idempotency_key=uuid.uuid4(),
        input_version=second_revision.version,
        request_hash="usage-test",
    )
    record(second_job, input_tokens=20, output_tokens=10)
    DocumentAudit.objects.create(
        revision=second_revision,
        action="ai.response",
        detail={"reasoning_tokens": 0, "cached_input_tokens": 0},
    )
    another_document = baseline.create(site)
    record(another_document.jobs.get(), input_tokens=999, output_tokens=999)
    expected = {
        "input_tokens": 120,
        "output_tokens": 60,
        "total_tokens": 180,
        "requests_count": 2,
        "reasoning_tokens": 30,
        "cached_input_tokens": 40,
        "audio_seconds": 0.0,
        "unknown_requests": 0,
    }
    assert document_token_usage(revision.elaborato_id) == expected
    assert services.serialize_revision(second_revision, full=True)["ai_usage"] == expected
    assert services.serialize_revision(revision, full=True)["ai_usage"] == expected
    assert services.serialize_job(second_job, include_result=True)["ai_usage"] == expected
    assert "ai_usage" not in services.serialize_revision(second_revision)


def test_unknown_consumption_is_not_invented_and_audio_seconds_are_separate(site):
    revision = baseline.create(site)
    job = revision.jobs.get()
    known = record(job, input_tokens=30, output_tokens=20)
    for response_id in (known.response_id, "unconfirmed-response"):
        DocumentAudit.objects.create(
            revision=revision,
            action="ai.stream_interrupted",
            detail={"response_id": response_id, "usage_unknown": True},
        )
    DocumentAudit.objects.create(
        revision=revision,
        action="ai.transcription",
        detail={"duration_seconds": 12.5, "usage": {"type": "duration", "seconds": 13}},
    )
    result = document_token_usage(revision.elaborato_id)
    assert result["total_tokens"] == 50
    assert result["unknown_requests"] == 1
    assert result["audio_seconds"] == 13


def test_legacy_missing_thinking_and_cache_breakdown_is_unknown_instead_of_zero(site):
    revision = baseline.create(site)
    record(revision.jobs.get(), input_tokens=100, output_tokens=50)
    DocumentAudit.objects.create(revision=revision, action="ai.response", detail={})
    result = document_token_usage(revision.elaborato_id)
    assert result["total_tokens"] == 150
    assert result["reasoning_tokens"] is None
    assert result["cached_input_tokens"] is None


def test_empty_counter_and_http_polling_keep_existing_document_authorization(site):
    revision = baseline.create(site)
    assert document_token_usage(revision.elaborato_id)["total_tokens"] == 0
    client = Client()
    token = login_and_get_token(email=site[1].email, password="test123")
    record(revision.jobs.get(), input_tokens=200, output_tokens=80)
    response = client.get(f"/api/v1/elaborati/revisions/{revision.pk}", **auth_header(token))
    assert response.status_code == 200
    assert response.json()["ai_usage"]["total_tokens"] == 280
    response = client.get(f"/api/v1/elaborati/jobs/{revision.jobs.get().pk}", **auth_header(token))
    assert response.status_code == 200
    assert response.json()["ai_usage"]["total_tokens"] == 280
    outsider_token = login_and_get_token(email=site[3].email, password="test123")
    response = client.get(
        f"/api/v1/elaborati/revisions/{revision.pk}", **auth_header(outsider_token)
    )
    assert response.status_code in (403, 404)
    assert "ai_usage" not in response.json()
