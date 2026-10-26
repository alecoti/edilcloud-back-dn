"""Revision clocks and unconfirmed artifact invalidation are separate invariants."""
from datetime import datetime, timedelta, timezone as utc

import pytest
from django.utils import timezone
from ninja.errors import HttpError

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.content import digest
from edilcloud.modules.elaborati.models import DraftPdfCache, ElaboratoRevision
from edilcloud.modules.elaborati.pdf_cache import display_pdf
from edilcloud.modules.elaborati.publication import publication_content_hash, publish_revision
from edilcloud.modules.elaborati.renderer import render_html
from tests import test_elaborati as baseline
from tests.test_elaborati_display_cache import prepare_display

pytestmark = pytest.mark.django_db
pytest_plugins = ["tests.test_elaborati"]


@pytest.mark.parametrize("at,expected", [
    ("2026-10-25T00:30:00+00:00", "25/10/2026 02:30 CEST"),
    ("2026-10-25T01:30:00+00:00", "25/10/2026 02:30 CET"),
    ("2027-01-01T00:30:00+00:00", "01/01/2027 01:30 CET"),
])
def test_revision_creation_is_not_document_creation_or_publication(site, provider, at, expected):
    original = baseline.generate(site)
    document_at = datetime(2025, 12, 31, 23, 30, tzinfo=utc.utc)
    original.elaborato.created_at = document_at
    original.elaborato.save(update_fields=["created_at"])
    original.state = "published"
    original.published_at = datetime(2026, 9, 1, 10, tzinfo=utc.utc)
    original.save(update_fields=["state", "published_at"])
    current = ElaboratoRevision.objects.create(
        elaborato=original.elaborato, number=1, created_by=site[1],
        template_snapshot=original.template_snapshot, editor_doc=original.editor_doc,
        evidence=original.evidence,
    )
    current.created_at = datetime.fromisoformat(at)
    current.save(update_fields=["created_at"])
    with timezone.override("Europe/Rome"):
        html = render_html(revision=current, profile=site[1], publication_state="published")
    intro = html.split('<div class="intro">', 1)[1].split('<div class="body">', 1)[0]
    assert "Revisione creata" in intro and expected in intro
    assert "EL-2025-" in intro and "01/01/2026" not in intro
    history = html.split("Registro revisioni", 1)[1]
    assert "Revisione creata" in history and "Pubblicazione" in history
    assert "01/09/2026 12:00 CEST" in history
    assert "</td><td>-</td></tr>" in history  # Never substitutes creation for publication.
    assert current.published_at is None
    data = services.serialize_revision(current, full=True, viewer_user_id=site[1].user_id)
    current_row = next(row for row in data["history"] if row["revision_id"] == str(current.pk))
    assert current_row["created_at"] == at and current_row["published_at"] is None


def legacy_hash(revision):
    document = revision.elaborato
    return digest({"editor": revision.editor_doc, "evidence": revision.evidence.get("bundle_hash"),
                   "template": revision.template_snapshot, "title": document.title,
                   "period_start": document.period_start, "period_end": document.period_end,
                   "style": document.style, "language": document.language})


def test_previous_format_neither_displays_nor_confers_publication_consent(site, provider, monkeypatch):
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **_: b"%PDF-QA-old-format")
    revision = baseline.generate(site)
    cached = prepare_display(site, revision)
    old = legacy_hash(revision)
    assert publication_content_hash(revision) != old
    DraftPdfCache.objects.filter(revision=revision).update(content_hash=old)
    revision.preview_content_hash = old
    revision.preview_signature.update(purpose="publication")
    revision.preview_expires_at = timezone.now() + timedelta(minutes=20)
    revision.save(update_fields=["preview_content_hash", "preview_signature", "preview_expires_at"])
    assert display_pdf(revision, user_id=site[1].user_id, profile_id=site[1].pk) is None
    data = services.serialize_revision(revision, full=True, viewer_user_id=site[1].user_id)
    assert not data["pdf_ready"] and not data["preview_ready"]
    with pytest.raises(HttpError) as error:
        publish_revision(profile=site[1], revision_id=revision.pk,
                         version=revision.version, preview_hash=cached.pdf_hash)
    assert error.value.status_code == 409
    revision.refresh_from_db()
    assert revision.state == "draft" and revision.drive_document_id is None


def test_frozen_publication_keeps_its_original_format_and_hash(site, provider, monkeypatch):
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **_: b"%PDF-QA-frozen-format")
    revision = baseline.prepare(site, baseline.generate(site))
    revision = publish_revision(profile=site[1], revision_id=revision.pk,
                                version=revision.version, preview_hash=revision.preview_hash)
    expected = revision.pdf_hash
    revision.preview_content_hash = legacy_hash(revision)
    revision.save(update_fields=["preview_content_hash"])
    data = services.serialize_revision(revision, full=True, viewer_user_id=site[1].user_id)
    assert data["pdf_ready"] and data["pdf_view_hash"] == expected
    with revision.preview_file.open("rb") as stream:
        assert stream.read() == b"%PDF-QA-frozen-format"
