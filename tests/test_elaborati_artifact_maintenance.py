"""Publication rollback copies and historical cache have narrowly owned cleanup."""
from datetime import timedelta
import os
from pathlib import Path
import uuid

from django.core.files.base import ContentFile
from django.utils import timezone
import pytest

from edilcloud.modules.elaborati.maintenance import (
    cleanup_publication_copies, cleanup_stale_display_cache,
)
from edilcloud.modules.elaborati.models import DocumentAudit, DraftPdfCache
from edilcloud.modules.elaborati.publication import publish_revision
from edilcloud.modules.elaborati.storage import private_document_storage
from edilcloud.modules.projects.models import ProjectDocument
from tests import test_elaborati as baseline
from tests.test_elaborati_display_cache import prepare_display

pytestmark = pytest.mark.django_db
from tests.test_elaborati import site, provider  # shared fixtures


def age(storage, name):
    old = (timezone.now() - timedelta(days=2)).timestamp()
    os.utime(storage.path(name), (old, old))


def copies():
    storage = ProjectDocument._meta.get_field("document").storage
    directory = Path(storage.path("elaborati/publications"))
    return storage, list(directory.glob("*.pdf")) if directory.exists() else []


def test_rolled_back_copy_is_owned_recoverable_and_never_claimed_published(
    site, provider, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kw: b"%PDF-test")
    revision = baseline.prepare(site, baseline.generate(site))
    original = DocumentAudit.objects.create

    def reject(**kwargs):
        if kwargs.get("action") == "published":
            raise ValueError("publication rollback")
        return original(**kwargs)

    monkeypatch.setattr(DocumentAudit.objects, "create", reject)
    with pytest.raises(ValueError, match="publication rollback"):
        publish_revision(profile=site[1], revision_id=revision.pk, version=revision.version,
                         preview_hash=revision.preview_hash)
    revision.refresh_from_db()
    assert revision.state == "draft" and revision.drive_document_id is None
    storage, paths = copies()
    assert len(paths) == 1 and paths[0].name.startswith(revision.pk.hex + "-")
    name = "elaborati/publications/" + paths[0].name
    assert cleanup_publication_copies() == []  # Fresh/in-flight candidates get a grace period.
    age(storage, name)
    assert cleanup_publication_copies() == [name] and storage.exists(name)
    assert cleanup_publication_copies(dry_run=False) == [name]
    assert not storage.exists(name) and revision.preview_file.storage.exists(revision.preview_file.name)
    assert cleanup_publication_copies(dry_run=False) == []


def test_committed_copy_and_user_upload_are_never_orphans(site, provider, monkeypatch):
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kw: b"%PDF-frozen")
    revision = baseline.prepare(site, baseline.generate(site))
    frozen = publish_revision(profile=site[1], revision_id=revision.pk,
                              version=revision.version, preview_hash=revision.preview_hash)
    storage = frozen.drive_document.document.storage
    name = frozen.drive_document.document.name
    age(storage, name)
    user_file = storage.save("projects/1/documents/unreferenced.pdf", ContentFile(b"user upload"))
    age(storage, user_file)
    unknown = storage.save("elaborati/publications/unrecognized.pdf", ContentFile(b"unknown"))
    age(storage, unknown)
    assert cleanup_publication_copies(dry_run=False) == []
    assert storage.exists(name) and storage.exists(user_file) and storage.exists(unknown)
    assert frozen.drive_document.document.open("rb").read() == b"%PDF-frozen"
    from django.conf import settings
    assert not (Path(settings.MEDIA_ROOT) / name).exists()
    assert (Path(settings.PRIVATE_STORAGE_ROOT) / name).read_bytes() == b"%PDF-frozen"
    from edilcloud.modules.projects.services import get_project_document_file_response
    response = get_project_document_file_response(profile=site[1],
        document_id=frozen.drive_document_id)
    code = f"EL-{frozen.elaborato.created_at.year}-{frozen.elaborato.number:04d}-Rev{frozen.number}.pdf"
    assert code in response["Content-Disposition"]
    response.close()


def test_stale_cache_dry_run_limits_and_shared_frozen_file_preservation(
    site, provider, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kw: b"%PDF-cache")
    draft = baseline.generate(site)
    live = prepare_display(site, draft)
    frozen = baseline.prepare(site, baseline.generate(site))
    frozen = publish_revision(profile=site[1], revision_id=frozen.pk,
                              version=frozen.version, preview_hash=frozen.preview_hash)
    DraftPdfCache.objects.create(revision=frozen, profile=site[1],
        content_hash="historical", pdf_hash=frozen.pdf_hash, pdf_file=frozen.preview_file.name,
        created_at=timezone.now())
    assert cleanup_stale_display_cache(limit=0) == []
    entries = cleanup_stale_display_cache(limit=1)
    assert len(entries) == 1 and entries[0]["revision_id"] == str(frozen.pk)
    assert DraftPdfCache.objects.filter(revision=frozen).exists()
    with django_capture_on_commit_callbacks(execute=True):
        assert cleanup_stale_display_cache(dry_run=False, limit=1) == entries
    assert not DraftPdfCache.objects.filter(revision=frozen).exists()
    assert private_document_storage().exists(frozen.preview_file.name)
    assert DraftPdfCache.objects.filter(revision=draft).exists()
    assert private_document_storage().exists(live.pdf_file)


def test_stale_cache_unreferenced_bytes_are_reclaimed_only_after_commit(
    site, provider, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kw: b"%PDF-cache")
    revision = baseline.generate(site)
    cached = prepare_display(site, revision)
    # Model a historical frozen revision with an obsolete, independently cached file.
    revision.state = "superseded"
    revision.preview_file = ""
    revision.save(update_fields=("state", "preview_file"))
    with django_capture_on_commit_callbacks(execute=True):
        assert len(cleanup_stale_display_cache(dry_run=False)) == 1
        assert private_document_storage().exists(cached.pdf_file)
    assert not private_document_storage().exists(cached.pdf_file)


def test_copy_cleanup_ignores_symlinks_and_subdirectories(site, tmp_path):
    storage = ProjectDocument._meta.get_field("document").storage
    name = f"elaborati/publications/{uuid.uuid4().hex}-{uuid.uuid4().hex}.pdf"
    directory = Path(storage.path(name)).parent
    directory.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "external.pdf"
    outside.write_bytes(b"must stay")
    try:
        Path(storage.path(name)).symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is not permitted by this Windows configuration")
    assert cleanup_publication_copies(dry_run=False) == []
    assert outside.read_bytes() == b"must stay" and (directory / Path(name).name).is_symlink()


def test_copy_cleanup_rejects_directory_junction_or_symlink(site, tmp_path):
    import subprocess

    storage = ProjectDocument._meta.get_field("document").storage
    directory = Path(storage.path("elaborati/publications"))
    directory.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside-publications"
    outside.mkdir()
    sentinel = outside / f"{uuid.uuid4().hex}-{uuid.uuid4().hex}.pdf"
    sentinel.write_bytes(b"must stay")
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(directory), str(outside)],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, result.stderr
    else:
        directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Directory delle copie"):
        cleanup_publication_copies(dry_run=False)
    assert sentinel.read_bytes() == b"must stay"


def test_worker_continues_after_maintenance_error(monkeypatch):
    from django.core.management import call_command
    from edilcloud.modules.elaborati import maintenance

    processed = []

    def unavailable(**kwargs):
        raise OSError("synthetic maintenance storage unavailable")

    monkeypatch.setattr(maintenance, "cleanup_stale_display_cache", unavailable)
    monkeypatch.setattr("edilcloud.modules.elaborati.management.commands.process_elaborati.process_batch",
                        lambda: processed.append(True) or 0)
    call_command("process_elaborati", once=True)
    assert processed == [True]


@pytest.mark.django_db(transaction=True)
def test_postgres_cleanup_skips_active_revision_writer(site, provider, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import connection, connections, transaction
    from edilcloud.modules.elaborati.models import ElaboratoRevision

    if connection.vendor != "postgresql":
        pytest.skip("Row-lock proof requires PostgreSQL")
    monkeypatch.setattr("edilcloud.modules.elaborati.renderer.render_pdf", lambda **kw: b"%PDF-lock")
    revision = baseline.generate(site)
    prepare_display(site, revision)
    revision.state = "superseded"
    revision.save(update_fields=("state",))
    storage = ProjectDocument._meta.get_field("document").storage
    orphan = storage.save(
        f"elaborati/publications/{revision.pk.hex}-{uuid.uuid4().hex}.pdf", ContentFile(b"copy")
    )
    age(storage, orphan)
    ready, release = Event(), Event()

    def hold_writer():
        try:
            with transaction.atomic():
                ElaboratoRevision.objects.select_for_update().get(pk=revision.pk)
                ready.set()
                assert release.wait(15)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        worker = executor.submit(hold_writer)
        try:
            assert ready.wait(10)
            assert cleanup_stale_display_cache(dry_run=False) == []
            assert cleanup_publication_copies(dry_run=False) == []
            assert DraftPdfCache.objects.filter(revision=revision).exists()
            assert storage.exists(orphan)
        finally:
            release.set()
        worker.result(timeout=10)
    assert len(cleanup_stale_display_cache(dry_run=False)) == 1
    assert cleanup_publication_copies(dry_run=False) == [orphan]
