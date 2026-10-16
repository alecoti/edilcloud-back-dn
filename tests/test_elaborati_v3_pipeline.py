from datetime import date
import uuid

import pytest
from django.test import Client

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.jobs import expire_jobs, process_job
from edilcloud.modules.elaborati.models import DocumentAIUsage, DocumentStep
from edilcloud.modules.elaborati.publication import publish_revision
from edilcloud.modules.elaborati.schemas import CreateRequest
from tests import test_elaborati as baseline
from tests.test_notifications_api import auth_header, login_and_get_token

site = baseline.site
pytestmark = pytest.mark.django_db


def create_v3(site, settings):
    settings.ELABORATI_WORKFLOW_VERSION = "v3.1"
    return services.create_elaborato(profile=site[1], payload=CreateRequest(
        idempotency_key=uuid.uuid4(), project_id=site[0].pk, document_type="daily_report",
        period_start=date.today(), period_end=date.today(),
    ))


def test_fast_zero_generates_draft_pdf_without_any_ai_or_token_reservation(site, settings, monkeypatch):
    site[-1].delete()
    revision = create_v3(site, settings)
    job = revision.jobs.get()
    assert job.workflow_version == "v3.1" and job.reserved_tokens == 0

    def forbidden(**kwargs):
        raise AssertionError("FAST_0 must never call AI")

    monkeypatch.setattr("edilcloud.modules.elaborati.intelligence_calls.structured_response", forbidden)
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-draft-v3")
    assert process_job(job.pk)
    job.refresh_from_db()
    revision.refresh_from_db()
    assert job.state == "completed", job.error_message
    assert revision.reasoning["path"] == "FAST_0" and revision.preview_signature["purpose"] == "draft"
    assert not DocumentAIUsage.objects.filter(job=job).exists()
    assert not job.evidence_items.filter(state="pending").exists()
    serialized = services.serialize_revision(revision, full=True, viewer_user_id=site[1].user_id)
    assert serialized["pdf_ready"] and not serialized["preview_ready"]
    from ninja.errors import HttpError

    with pytest.raises(HttpError, match="versione finale"):
        publish_revision(profile=site[1], revision_id=revision.pk, version=revision.version,
                         preview_hash=revision.preview_hash)
    assert job.steps.get(key="document_content").state == "completed"


def test_crash_during_rendering_reuses_completed_document_without_rebuying_ai(site, settings, monkeypatch):
    site[-1].delete()
    revision = create_v3(site, settings)
    job = revision.jobs.get()
    renders = []

    def rendering(**kwargs):
        renders.append(1)
        if len(renders) == 1:
            raise OSError("Rendering crashed")
        return b"%PDF-recovered"

    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", rendering)
    process_job(job.pk)
    job.refresh_from_db()
    assert job.state == "failed" and job.steps.get(key="document_content").state == "completed"
    resumed = services.resume_job(profile=site[1], job_id=job.pk, version=revision.version)
    assert resumed.pk == job.pk and resumed.state == "queued"
    assert services.resume_job(profile=site[1], job_id=job.pk, version=revision.version).pk == job.pk
    # If resumption recollects evidence or regenerates content, this fails.
    monkeypatch.setattr("edilcloud.modules.elaborati.pipeline_v3.build_inventory",
                        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Already checkpointed")))
    assert process_job(job.pk)
    job.refresh_from_db()
    assert job.state == "completed", job.error_message
    assert len(renders) == 2 and not job.usage.exists()


def test_resume_api_refuses_changed_draft_and_ambiguous_remote_result(site, settings):
    from ninja.errors import HttpError

    revision = create_v3(site, settings)
    job = revision.jobs.get()
    job.state = "failed"
    job.save()
    step = job.steps.create(key="provider", kind="write", input_hash="x", state="unknown")
    step.attempts.create(number=1, state="unknown", input_hash="x", model="gpt-6-luna")
    client = Client()
    headers = auth_header(login_and_get_token(email=site[1].user.email, password="test123"))
    url = f"/api/v1/elaborati/jobs/{job.pk}/resume"
    response = client.post(url, data={"version": revision.version}, content_type="application/json", **headers)
    assert response.status_code == 409
    assert not services.serialize_job(job)["can_resume"]
    step.attempts.update(state="rejected")
    step.state = "failed"
    step.save()
    with pytest.raises(HttpError, match="bozza è cambiata"):
        services.resume_job(profile=site[1], job_id=job.pk, version=revision.version + 1)
    with pytest.raises(HttpError):
        services.resume_job(profile=site[3], job_id=job.pk, version=revision.version)
    success = client.post(url, data={"version": revision.version}, content_type="application/json", **headers)
    assert success.status_code == 200 and success.json()["id"] == str(job.pk)
    assert revision.jobs.count() == 1


def test_expired_v3_work_resumes_but_unknown_provider_outcome_is_not_replayed(site, settings):
    from datetime import timedelta
    from django.utils import timezone

    revision = create_v3(site, settings)
    job = revision.jobs.get()
    job.state = "running"
    job.lease_expires_at = timezone.now() - timedelta(minutes=1)
    job.save()
    step = DocumentStep.objects.create(job=job, key="local", kind="local", input_hash="x",
                                       contract_version="v3.1", state="running")
    assert expire_jobs() == 1
    job.refresh_from_db()
    step.refresh_from_db()
    assert job.state == "queued" and step.state == "failed"
    job.state = "running"
    job.lease_expires_at = timezone.now() - timedelta(minutes=1)
    job.save()
    step.attempts.create(number=1, state="sent", input_hash="x", model="gpt-6-luna")
    assert expire_jobs() == 1
    job.refresh_from_db()
    step.refresh_from_db()
    assert job.state == "failed" and step.state == "unknown"


def test_pdf_endpoint_rejects_stale_content_and_exposes_no_extra_ai(site, settings, monkeypatch):
    site[-1].delete()
    revision = create_v3(site, settings)
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-valid")
    assert process_job(revision.jobs.get().pk)
    revision.refresh_from_db()
    client = Client()
    headers = auth_header(login_and_get_token(email=site[1].user.email, password="test123"))
    response = client.get(f"/api/v1/elaborati/revisions/{revision.pk}/pdf", **headers)
    assert response.status_code == 200
    revision.editor_doc["attrs"]["documentTitle"] = "Changed content"
    revision.save()
    stale = client.get(f"/api/v1/elaborati/revisions/{revision.pk}/pdf", **headers)
    assert stale.status_code == 409
    assert not revision.jobs.get().usage.exists()
