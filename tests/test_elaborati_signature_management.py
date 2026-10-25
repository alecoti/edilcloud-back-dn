import hashlib
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import connection, connections, transaction
from django.test import Client
from ninja.errors import HttpError

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.publication import publish_revision
from tests import test_elaborati as baseline
from tests.test_elaborati import provider, site  # noqa: F401
from tests.test_notifications_api import auth_header, login_and_get_token

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("operation", ["replace", "remove"])
def test_changed_personal_signature_invalidates_preview_without_publishing(site, provider, monkeypatch, operation):
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf",
                        lambda **kwargs: b"%PDF-synthetic-signature-management")
    revision = baseline.prepare(site, baseline.generate(site), signed=True)
    if operation == "replace":
        services.save_signature(user=site[1].user,
                                strokes=[[[.2, .1], [.4, .7], [.6, .5], [.8, .2]]])
    else:
        services.delete_signature(user=site[1].user)
    assert not services.serialize_revision(
        revision, full=True, viewer_user_id=site[1].user_id)["preview_ready"]
    with pytest.raises(HttpError) as error:
        publish_revision(profile=site[1], revision_id=revision.pk,
                         version=revision.version, preview_hash=revision.preview_hash,
                         confirm_signature=True)
    assert error.value.status_code == 409
    assert ("cambiata" if operation == "replace" else "rimossa") in error.value.message
    revision.refresh_from_db()
    assert revision.state == "draft" and not revision.drive_document_id


def test_removal_does_not_change_a_published_signed_pdf(site, provider, monkeypatch):
    raw = b"%PDF-synthetic-frozen-signature"
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: raw)
    revision = baseline.prepare(site, baseline.generate(site), signed=True)
    frozen = publish_revision(profile=site[1], revision_id=revision.pk,
        version=revision.version, preview_hash=revision.preview_hash, confirm_signature=True)
    audit = frozen.signature_audit
    services.delete_signature(user=site[1].user)
    frozen.refresh_from_db()
    assert frozen.state == "signed" and frozen.signature_audit == audit
    assert frozen.pdf_hash == hashlib.sha256(raw).hexdigest()
    with frozen.drive_document.document.open("rb") as file:
        assert file.read() == raw
    assert publish_revision(profile=site[1], revision_id=revision.pk,
        version=revision.version, preview_hash=revision.preview_hash).pk == frozen.pk


def test_personal_signature_http_is_not_cacheable(site):
    client = Client()
    token = login_and_get_token(email=site[1].user.email, password="test123")
    headers = auth_header(token)
    strokes = [[[.1, .1], [.2, .8], [.7, .3], [.9, .9]]]
    for method in ["get", "put", "get", "delete"]:
        kwargs = {"data":{"strokes":strokes}, "content_type":"application/json"} if method=="put" else {}
        response = getattr(client, method)("/api/v1/elaborati/signature", **headers, **kwargs)
        assert response.status_code == 200
        assert response["Cache-Control"] == "private, no-store"
        assert response["X-Content-Type-Options"] == "nosniff"


@pytest.mark.django_db(transaction=True)
def test_publication_waits_for_concurrent_signature_removal(site, provider, monkeypatch):
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock behavior must be observed on PostgreSQL.")
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf",
                        lambda **kwargs: b"%PDF-synthetic-concurrent-signature")
    revision = baseline.prepare(site, baseline.generate(site), signed=True)
    owner = site[1]

    def publish_in_other_connection():
        try:
            publish_revision(profile=owner, revision_id=revision.pk,
                version=revision.version, preview_hash=revision.preview_hash, confirm_signature=True)
            return 200, ""
        except HttpError as error:
            return error.status_code, error.message
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            type(owner.user).objects.select_for_update().get(pk=owner.user_id)
            pending = executor.submit(publish_in_other_connection)
            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline and not pending.done():
                with connection.cursor() as cursor:
                    # PostgreSQL caches activity snapshots within a transaction.
                    # Refresh this observer before checking the other connection.
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute("""
                        SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                        WHERE datname=current_database() AND pid<>pg_backend_pid()
                        AND wait_event_type='Lock' AND query LIKE '%%identity_user%%')
                    """)
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                time.sleep(.02)
            assert waiting, (
                f"Publisher finished before waiting: {pending.result()}" if pending.done()
                else "Publication must wait for concurrent signature removal"
            )
            services.delete_signature(user=owner.user)
        status, message = pending.result(timeout=5)
    assert status == 409 and "rimossa" in message
    revision.refresh_from_db()
    assert revision.state == "draft" and not revision.drive_document_id
