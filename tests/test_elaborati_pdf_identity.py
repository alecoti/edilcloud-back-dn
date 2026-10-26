"""The download URL must identify the exact bytes shown for confirmation."""
import pytest
from django.test import Client

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.publication import publish_revision
from tests import test_elaborati as baseline
from tests.test_elaborati import provider, site  # noqa: F401
from tests.test_notifications_api import auth_header, login_and_get_token

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("frozen", [False, True])
def test_pdf_rejects_a_different_hash_and_unknown_purpose(site, provider, monkeypatch, frozen):
    raw = b"%PDF-synthetic-identity-check"
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: raw)
    revision = baseline.prepare(site, baseline.generate(site), signed=True)
    if frozen:
        revision = publish_revision(profile=site[1], revision_id=revision.pk,
            version=revision.version, preview_hash=revision.preview_hash, confirm_signature=True)
        services.delete_signature(user=site[1].user)
    client = Client()
    token = login_and_get_token(email="elaborati.owner@example.com", password="test123")
    headers = auth_header(token)
    path = f"/api/v1/elaborati/revisions/{revision.pk}/pdf"
    expected = revision.pdf_hash if frozen else revision.preview_hash
    good = client.get(path, {"hash": expected, "purpose": "publication"}, **headers)
    assert good.status_code == 200
    assert b"".join(good.streaming_content) == raw
    assert good["Cache-Control"] == "private, no-store"
    wrong = client.get(path, {"hash": "0" * 64}, **headers)
    assert wrong.status_code == 409
    assert wrong.json() == {"detail": "Il PDF è cambiato. Ricarica il documento."}
    assert client.get(path, {"purpose": "unknown"}, **headers).status_code == 400
    legacy = client.get(path, **headers)
    assert legacy.status_code == 200
    assert b"".join(legacy.streaming_content) == raw
    data = services.serialize_revision(revision, full=True, viewer_user_id=site[1].user_id)
    assert data["pdf_view_hash"] == expected
