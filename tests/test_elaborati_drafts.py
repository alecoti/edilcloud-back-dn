"""Draft lifecycle and token-free publication, independent of AI verdicts."""

from copy import deepcopy
import hashlib
import uuid

import pytest
from django.test import Client
from ninja.errors import HttpError

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.jobs import process_job
from edilcloud.modules.elaborati.models import DocumentAIUsage, DocumentAudit
from edilcloud.modules.elaborati.publication import publish_revision
from edilcloud.modules.elaborati.schemas import ActionRequest, SaveRequest
from tests import test_elaborati as baseline
from tests.test_notifications_api import auth_header, login_and_get_token

site = baseline.site
provider = baseline.provider
pytestmark = pytest.mark.django_db


def no_provider(**kwargs):
    raise AssertionError("This operation must not call an AI provider")


def test_open_save_preview_publish_and_new_revision_never_call_ai(
    site, provider, monkeypatch, settings
):
    revision = baseline.generate(site)
    owner = site[1]
    initial_calls = len(provider)
    assert initial_calls == 3
    monkeypatch.setattr("edilcloud.modules.elaborati.engine.structured_response", no_provider)
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-no-ai"
    )
    # An exhausted AI budget cannot prevent rendering/publication either.
    settings.AI_TOKEN_QUOTA_ENFORCED = True
    from edilcloud.modules.billing.services import entitlement_snapshot

    monkeypatch.setattr(
        "edilcloud.modules.billing.services.ai_quota_is_unlimited", lambda account: False
    )
    monkeypatch.setattr(
        "edilcloud.modules.billing.services.entitlement_snapshot",
        lambda account: {
            **entitlement_snapshot(account),
            "ai_tokens": {"remaining_this_period": -10},
        },
    )
    client = Client()
    token = login_and_get_token(email=owner.user.email, password="test123")
    headers = auth_header(token)
    jobs_before = revision.jobs.count()
    for _ in range(3):
        response = client.get(f"/api/v1/elaborati/revisions/{revision.pk}", **headers)
        assert response.status_code == 200
    assert revision.jobs.count() == jobs_before
    edited = deepcopy(revision.editor_doc)
    edited["content"][1]["content"][0]["text"] += " Annotazione manuale dell'autore."
    revision = services.save_revision(
        profile=owner,
        revision_id=revision.pk,
        payload=SaveRequest(version=revision.version, editor_doc=edited),
    )
    assert revision.quality["needs_verification"]
    old_quality = deepcopy(revision.quality)
    request = ActionRequest(
        idempotency_key=uuid.uuid4(), version=revision.version, action="preview"
    )
    job = services.request_action(profile=owner, revision_id=revision.pk, payload=request)
    assert job.reserved_tokens == 0
    assert process_job(job.pk)
    job.refresh_from_db()
    revision.refresh_from_db()
    assert job.state == "completed", job.error_message
    assert job.result["ai_used"] is False and job.result["preview_ready"]
    assert revision.quality == old_quality, "A PDF preview must not replace the optional AI review"
    assert not DocumentAIUsage.objects.filter(job=job).exists()
    version, preview = revision.version, revision.preview_hash
    # A harmless editor flush must not invalidate a valid PDF.
    unchanged = deepcopy(revision.editor_doc)
    unchanged["content"][1]["attrs"]["textAlign"] = None
    revision = services.save_revision(
        profile=owner,
        revision_id=revision.pk,
        payload=SaveRequest(version=version, editor_doc=unchanged),
    )
    assert revision.version == version and revision.preview_hash == preview
    published = publish_revision(
        profile=owner, revision_id=revision.pk, version=version, preview_hash=preview
    )
    assert published.state == "published"
    with published.drive_document.document.open("rb") as stream:
        assert hashlib.sha256(stream.read()).hexdigest() == preview
    new = services.new_revision(profile=owner, revision_id=revision.pk)
    assert new.state == "draft" and not new.jobs.exists()
    assert len(provider) == initial_calls


def test_only_explicit_verify_requests_call_the_ai_verifier(site, provider):
    revision = baseline.generate(site)
    calls = len(provider)
    job = services.request_action(
        profile=site[1],
        revision_id=revision.pk,
        payload=ActionRequest(
            idempotency_key=uuid.uuid4(), version=revision.version, action="verify"
        ),
    )
    assert process_job(job.pk)
    assert len(provider) == calls + 1 and provider[-1][0] == "document_quality"


def test_preview_readiness_matches_viewer_signature_and_document(site, provider, monkeypatch):
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-signed"
    )
    revision = baseline.prepare(site, baseline.generate(site), signed=True)
    owner = site[1]
    assert services.serialize_revision(revision, full=True, viewer_user_id=owner.user_id)[
        "preview_ready"
    ]
    assert not services.serialize_revision(revision, full=True, viewer_user_id=site[2].user_id)[
        "preview_ready"
    ]
    services.save_signature(
        user=owner.user, strokes=[[[0.2, 0.2], [0.5, 0.9], [0.8, 0.3], [0.9, 0.4]]]
    )
    assert not services.serialize_revision(revision, full=True, viewer_user_id=owner.user_id)[
        "preview_ready"
    ]
    revision.preview_signature = {"prepared_by_user_id": owner.user_id}
    revision.editor_doc["attrs"]["documentTitle"] = "Titolo aggiornato"
    assert not services.serialize_revision(revision, full=True, viewer_user_id=owner.user_id)[
        "preview_ready"
    ]


def test_empty_draft_reports_a_technical_error_without_requesting_ai(site, provider, monkeypatch):
    revision = baseline.generate(site)
    revision.editor_doc = {"type": "doc", "content": []}
    revision.save()
    monkeypatch.setattr("edilcloud.modules.elaborati.engine.structured_response", no_provider)
    job = services.request_action(
        profile=site[1],
        revision_id=revision.pk,
        payload=ActionRequest(
            idempotency_key=uuid.uuid4(), version=revision.version, action="preview"
        ),
    )
    assert process_job(job.pk)
    job.refresh_from_db()
    assert job.state == "failed" and "vuota" in job.error_message
    assert not DocumentAIUsage.objects.filter(job=job).exists()


def test_delete_draft_cancels_queued_work_hides_all_endpoints_and_retains_usage(site):
    revision = baseline.create(site)
    owner = site[1]
    job = revision.jobs.get()
    usage = DocumentAIUsage.objects.create(
        job=job,
        workspace=owner.workspace,
        response_id=str(uuid.uuid4()),
        stage="document_reasoning",
        input_tokens=20,
        output_tokens=5,
        total_tokens=25,
    )
    client = Client()
    token = login_and_get_token(email=owner.user.email, password="test123")
    headers = auth_header(token)
    response = client.delete(
        f"/api/v1/elaborati/revisions/{revision.pk}?version={revision.version}", **headers
    )
    assert response.status_code == 200 and response.json()["deleted"]
    revision.refresh_from_db()
    job.refresh_from_db()
    assert revision.state == "deleted" and job.state == "failed" and job.reserved_tokens == 0
    assert not process_job(job.pk)
    assert DocumentAIUsage.objects.get(pk=usage.pk).total_tokens == 25
    assert DocumentAudit.objects.filter(
        revision=revision, action="draft.deleted", actor=owner
    ).exists()
    assert services.list_elaborati(profile=owner)["total"] == 0
    for suffix in (
        f"revisions/{revision.pk}",
        f"revisions/{revision.pk}/pdf",
        f"revisions/{revision.pk}/sources/photo:1",
        f"jobs/{job.pk}",
    ):
        assert client.get(f"/api/v1/elaborati/{suffix}", **headers).status_code == 404
    next_document = baseline.create(site)
    assert next_document.elaborato.number == revision.elaborato.number + 1


def test_draft_deletion_enforces_role_version_and_running_job_guards(site):
    revision = baseline.create(site)
    for profile in (site[2], site[3]):
        with pytest.raises(HttpError) as exc:
            services.delete_draft(
                profile=profile, revision_id=revision.pk, version=revision.version
            )
        assert exc.value.status_code in {403, 404}
    with pytest.raises(HttpError) as exc:
        services.delete_draft(
            profile=site[1], revision_id=revision.pk, version=revision.version + 1
        )
    assert exc.value.status_code == 409
    revision.jobs.update(state="running")
    with pytest.raises(HttpError) as exc:
        services.delete_draft(profile=site[1], revision_id=revision.pk, version=revision.version)
    assert exc.value.status_code == 409
    revision.refresh_from_db()
    assert revision.state == "draft"


def test_deleting_a_new_draft_preserves_published_pdf_and_allows_later_revision(
    site, provider, monkeypatch
):
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-keep-history"
    )
    original = baseline.prepare(site, baseline.generate(site))
    published = publish_revision(
        profile=site[1],
        revision_id=original.pk,
        version=original.version,
        preview_hash=original.preview_hash,
    )
    with pytest.raises(HttpError) as exc:
        services.delete_draft(profile=site[1], revision_id=published.pk, version=published.version)
    assert exc.value.status_code == 409
    draft = services.new_revision(profile=site[1], revision_id=published.pk)
    services.delete_draft(profile=site[1], revision_id=draft.pk, version=draft.version)
    page = services.list_elaborati(profile=site[1])
    assert page["total"] == 1 and page["items"][0]["revision_id"] == str(published.pk)
    detail = services.serialize_revision(published, full=True)
    assert str(draft.pk) not in {r["revision_id"] for r in detail["history"]}
    with published.drive_document.document.open("rb") as stream:
        assert stream.read() == b"%PDF-keep-history"
    next_draft = services.new_revision(profile=site[1], revision_id=published.pk)
    assert next_draft.number == draft.number + 1
