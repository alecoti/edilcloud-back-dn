"""Display bytes survive publication preparation, never confer publication consent."""

from copy import deepcopy
from datetime import timedelta
import uuid

import pytest
from django.test import Client
from django.utils import timezone
from ninja.errors import HttpError

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.jobs import process_job
from edilcloud.modules.elaborati.models import DocumentAudit, DraftPdfCache
from edilcloud.modules.elaborati.pdf_cache import display_pdf, prepared_profile
from edilcloud.modules.elaborati.publication import publish_revision
from edilcloud.modules.elaborati.schemas import ActionRequest
from edilcloud.modules.elaborati.storage import private_document_storage
from edilcloud.modules.projects.models import ProjectMember
from edilcloud.modules.workspaces.models import Profile
from tests import test_elaborati as baseline
from tests.test_notifications_api import auth_header, login_and_get_token

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.test_elaborati"]


def prepare_display(site, revision):
    job = services.request_action(
        profile=site[1],
        revision_id=revision.pk,
        payload=ActionRequest(
            idempotency_key=uuid.uuid4(),
            version=revision.version,
            action="preview",
            preview_purpose="draft",
        ),
    )
    process_job(job.pk)
    job.refresh_from_db()
    assert job.state == "completed", job.error_message
    revision.refresh_from_db()
    return display_pdf(revision, user_id=site[1].user_id, profile_id=site[1].pk)


def test_display_survives_signed_preview_and_expiry_without_another_render(
    site, provider, monkeypatch, django_capture_on_commit_callbacks
):
    rendered = []

    def render(**kwargs):
        rendered.append(kwargs["publication_state"])
        return b"%PDF-synthetic-" + kwargs["publication_state"].encode()

    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", render)
    with django_capture_on_commit_callbacks(execute=True):
        revision = baseline.generate(site)
        cached = prepare_display(site, revision)
        assert cached and revision.preview_expires_at is None
        revision = baseline.prepare(site, revision, signed=True)
        assert revision.preview_hash != cached.pdf_hash
    assert private_document_storage().exists(cached.pdf_file)
    revision.preview_expires_at = timezone.now() - timedelta(minutes=1)
    revision.save(update_fields=["preview_expires_at"])
    data = services.serialize_revision(
        revision, full=True, viewer_user_id=site[1].user_id, viewer_profile_id=site[1].pk
    )
    assert data["pdf_ready"] and not data["preview_ready"]
    assert data["pdf_view_hash"] == cached.pdf_hash
    headers = auth_header(
        login_and_get_token(email="elaborati.owner@example.com", password="test123")
    )
    path = f"/api/v1/elaborati/revisions/{revision.pk}/pdf"
    response = Client().get(path, {"purpose": "display", "hash": cached.pdf_hash}, **headers)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == b"%PDF-synthetic-draft"
    assert response["Cache-Control"] == "private, no-store"
    assert (
        Client()
        .get(path, {"purpose": "publication", "hash": revision.preview_hash}, **headers)
        .status_code
        == 409
    )
    assert prepare_display(site, revision) == cached
    assert rendered == ["draft", "signed"]
    assert DraftPdfCache.objects.filter(revision=revision).count() == 1


def test_changed_content_and_missing_file_never_reuse_a_cache_entry(site, provider, monkeypatch):
    renders = []
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf",
        lambda **kwargs: renders.append(True) or b"%PDF-synthetic-display",
    )
    revision = baseline.generate(site)
    cached = prepare_display(site, revision)
    original = deepcopy(revision.editor_doc)
    revision.editor_doc["content"].append(
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Nuova annotazione non inclusa nel PDF."}],
        }
    )
    assert display_pdf(revision, user_id=site[1].user_id, profile_id=site[1].pk) is None
    revision.editor_doc = original
    private_document_storage().delete(cached.pdf_file)
    assert display_pdf(revision, user_id=site[1].user_id, profile_id=site[1].pk) is None
    replacement = prepare_display(site, revision)
    assert replacement.pdf_file != cached.pdf_file and len(renders) == 2
    assert DraftPdfCache.objects.filter(revision=revision).count() == 1


def test_publication_and_legacy_display_are_bound_to_the_requesting_profile(
    site, provider, monkeypatch
):
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-profile-test"
    )
    revision = baseline.generate(site)
    prepare_display(site, revision)
    alias = Profile.objects.create(
        user=site[1].user,
        workspace=site[3].workspace,
        email="elaborati.alias@example.com",
        role="o",
    )
    ProjectMember.objects.create(project=site[0], profile=alias, role="o")
    assert display_pdf(revision, user_id=site[1].user_id, profile_id=alias.pk) is None
    DraftPdfCache.objects.filter(revision=revision).delete()
    revision.preview_signature.pop("prepared_by_profile_id")
    assert display_pdf(revision, user_id=site[1].user_id, profile_id=site[1].pk) is None
    assert (
        prepared_profile({"prepared_by_user_id": site[1].user_id, "prepared_by_profile_id": True})
        is None
    )
    revision.refresh_from_db()
    revision = baseline.prepare(site, revision, signed=True)
    data = services.serialize_revision(
        revision, full=True, viewer_user_id=site[1].user_id, viewer_profile_id=alias.pk
    )
    assert not data["preview_ready"]
    with pytest.raises(HttpError) as exc:
        publish_revision(
            profile=alias,
            revision_id=revision.pk,
            version=revision.version,
            preview_hash=revision.preview_hash,
            confirm_signature=True,
        )
    assert exc.value.status_code == 409
    assert "profilo attivo" in exc.value.message
    revision.refresh_from_db()
    assert revision.state == "draft" and revision.drive_document_id is None


def test_publication_releases_display_cache_after_commit_and_preserves_frozen_file(
    site, provider, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf",
        lambda **kwargs: b"%PDF-synthetic-" + kwargs["publication_state"].encode(),
    )
    with django_capture_on_commit_callbacks(execute=True):
        revision = baseline.generate(site)
        cached = prepare_display(site, revision)
        revision = baseline.prepare(site, revision, signed=True)
    assert private_document_storage().exists(cached.pdf_file)
    with django_capture_on_commit_callbacks(execute=True):
        frozen = publish_revision(
            profile=site[1],
            revision_id=revision.pk,
            version=revision.version,
            preview_hash=revision.preview_hash,
            confirm_signature=True,
        )
        assert not DraftPdfCache.objects.filter(revision=revision).exists()
        assert private_document_storage().exists(cached.pdf_file)
    assert not private_document_storage().exists(cached.pdf_file)
    assert frozen.preview_file.open("rb").read() == b"%PDF-synthetic-signed"


def test_cache_and_display_bytes_survive_a_rolled_back_publication(
    site, provider, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-rollback-test"
    )
    with django_capture_on_commit_callbacks(execute=True):
        revision = baseline.generate(site)
        cached = prepare_display(site, revision)
        revision = baseline.prepare(site, revision)
    original_create = DocumentAudit.objects.create

    def reject_publication(**kwargs):
        if kwargs.get("action") == "published":
            raise ValueError("synthetic publication audit rejection")
        return original_create(**kwargs)

    monkeypatch.setattr(DocumentAudit.objects, "create", reject_publication)
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(ValueError, match="synthetic publication audit rejection"):
            publish_revision(
                profile=site[1],
                revision_id=revision.pk,
                version=revision.version,
                preview_hash=revision.preview_hash,
            )
    revision.refresh_from_db()
    assert revision.state == "draft" and revision.drive_document_id is None
    assert DraftPdfCache.objects.filter(revision=revision, pdf_file=cached.pdf_file).exists()
    assert private_document_storage().exists(cached.pdf_file)
