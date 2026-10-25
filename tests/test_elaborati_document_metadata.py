from copy import deepcopy
from datetime import timedelta
import hashlib

import pytest
from django.core.files.base import ContentFile
from django.test import Client
from django.utils import timezone
from django.utils.http import content_disposition_header

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.documentary_register import manifest, people_register
from edilcloud.modules.elaborati.filenames import pdf_filename
from edilcloud.modules.elaborati.publication import publication_content_hash
from edilcloud.modules.elaborati.renderer import render_html
from tests import test_elaborati as baseline
from tests.test_notifications_api import auth_header, login_and_get_token

site = baseline.site
provider = baseline.provider
pytestmark = pytest.mark.django_db


def test_creation_dates_remain_distinct_from_content_period_and_last_update(site, provider):
    revision = baseline.generate(site)
    created = revision.created_at
    services.ElaboratoRevision.objects.filter(pk=revision.pk).update(
        updated_at=created + timedelta(days=3)
    )
    revision.refresh_from_db()
    detail = services.serialize_revision(revision, full=True, viewer_user_id=site[1].user_id)
    listed = services.list_elaborati(profile=site[1])["items"][0]
    assert detail["created_at"] == listed["created_at"] == revision.elaborato.created_at.isoformat()
    assert detail["revision_created_at"] == listed["revision_created_at"] == created.isoformat()
    assert detail["updated_at"] != detail["revision_created_at"]
    assert detail["pdf_filename"] == pdf_filename(revision)


def test_cover_and_people_register_use_frozen_roles_without_promoting_current_roles(site, provider):
    revision = baseline.generate(site)
    revision.elaborato.author_snapshot = {
        "person_name": "Laura Verdi", "company_name": "Impresa Storica",
        "qualification": "Ingegnere", "role_labels": ["CSE"],
    }
    source = next(s for s in revision.evidence["sources"] if s["kind"] == "post")
    source["actor"] = {
        "person_name": "Laura Verdi", "company_name": "Impresa Storica",
        "qualification": "Ingegnere", "role_labels": ["CSE"],
        "identity_state": "captured",
    }
    catalogue = next(s for s in revision.evidence["sources"] if s["kind"] == "member")
    catalogue["data"].update({
        "name": "Laura Verdi", "company": "Impresa Attuale", "qualification": "Tecnico",
        "professional_roles": ["rspp"], "roles_are_current_catalogue": True,
    })
    before = deepcopy(revision.evidence)
    html = render_html(revision=revision, profile=site[1])
    assert "Laura Verdi · Impresa Storica · Ingegnere · CSE" in html
    assert "Soggetti e incarichi di riferimento" in html and "RSPP" in html
    assert "Anagrafica alla raccolta; validità nel periodo non documentata" in html
    assert "Attribuzione nelle fonti citate" in html
    assert revision.evidence == before
    rows = people_register(revision.evidence, {source["id"]})
    assert any(row["scope"] == "source" and row["professional_role_labels"] == ["CSE"] for row in rows)
    assert any(row["scope"] == "catalogue" and row["professional_role_labels"] == ["RSPP"] for row in rows)
    frozen = manifest(revision)
    assert catalogue["id"] in {s["id"] for s in frozen["sources"]}


def test_people_register_still_exposes_cited_attribution_without_member_catalogue(site, provider):
    revision = baseline.generate(site)
    revision.evidence["sources"] = [s for s in revision.evidence["sources"] if s["kind"] != "member"]
    source = next(s for s in revision.evidence["sources"] if s["kind"] == "post")
    source["actor"] = {"person_name": "Esterno Documentato", "company_name": "Impresa X", "qualification": "Caposquadra", "role_labels": []}
    html = render_html(revision=revision, profile=site[1])
    assert "Soggetti e incarichi di riferimento" in html
    assert "Esterno Documentato" in html and "Caposquadra" in html


def test_pdf_view_and_download_keep_human_filename_and_access_checks(site, provider):
    revision = baseline.generate(site)
    owner = site[1]
    data = b"%PDF-filename-regression"
    revision.preview_file.save("uuid-internal.pdf", ContentFile(data), save=False)
    revision.preview_hash = hashlib.sha256(data).hexdigest()
    revision.preview_content_hash = publication_content_hash(revision)
    revision.preview_expires_at = timezone.now() + timedelta(minutes=20)
    revision.preview_signature = {"prepared_by_user_id": owner.user_id, "purpose": "draft"}
    revision.save()
    filename = pdf_filename(revision)
    assert filename.startswith("EL-") and "Rev-0" in filename
    assert revision.elaborato.period_start.isoformat() in filename
    assert "uuid-internal" not in filename and filename.endswith(".pdf")
    client = Client()
    headers = auth_header(login_and_get_token(email=owner.user.email, password="test123"))
    endpoint = f"/api/v1/elaborati/revisions/{revision.pk}/pdf"
    for download in (False, True):
        response = client.get(endpoint, {"download": str(download).lower()}, **headers)
        assert response.status_code == 200
        assert response["Content-Disposition"] == content_disposition_header(download, filename)
        assert b"".join(response.streaming_content) == data
    assert client.get(endpoint, {"download": "true"}).status_code == 401
