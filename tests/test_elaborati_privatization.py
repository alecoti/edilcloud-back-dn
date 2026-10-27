"""Issued bytes and frozen metadata survive transfer, rollback and retry."""

from copy import deepcopy
import hashlib
from io import StringIO
from pathlib import Path
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.management import call_command, CommandError
import pytest

from edilcloud.modules.elaborati.models import DocumentAudit
from edilcloud.modules.elaborati.privatization import ACTION, RETIRED_ACTION, transfer_revision
from edilcloud.modules.elaborati.publication_transfer import PublicationTransfer
from edilcloud.modules.projects.models import ProjectDocument, PostAttachment
from tests import test_elaborati as baseline

pytestmark = pytest.mark.django_db(transaction=True)
site = baseline.site
DATA = b"%PDF issued synthetic immutable fixture"


def issued(site, settings, *, legacy=False):
    revision = baseline.create(site)
    logical = (
        f"projects/{site[0].pk}/documents/old-{uuid.uuid4().hex}.pdf"
        if legacy
        else f"elaborati/publications/{revision.pk.hex}-{uuid.uuid4().hex}.pdf"
    )
    public = FileSystemStorage(location=settings.MEDIA_ROOT)
    public.save(logical, ContentFile(DATA))
    document = ProjectDocument.objects.create(
        project=site[0],
        uploaded_by=site[1],
        title="Issued fixture",
        document=logical,
        file_size=len(DATA),
    )
    # Explicit historical fixture, not a new publication using the private adapter.
    ProjectDocument.objects.filter(pk=document.pk).update(file_size=len(DATA))
    revision.state = "signed"
    revision.drive_document = document
    revision.pdf_hash = hashlib.sha256(DATA).hexdigest()
    revision.frozen_manifest = {"old_storage_reference": logical, "immutable": True}
    revision.signature_audit = {"synthetic": True, "fingerprint": "retained"}
    revision.save()
    return revision, document, logical


def frozen(revision):
    revision.refresh_from_db()
    return deepcopy({key: value for key, value in vars(revision).items() if key != "_state"})


@pytest.mark.parametrize("legacy", [False, True])
def test_dry_run_transfer_and_repeat_preserve_frozen_pdf_and_metadata(site, settings, legacy):
    revision, document, old = issued(site, settings, legacy=legacy)
    before = frozen(revision)
    document.refresh_from_db()
    metadata = (document.created_at, document.updated_at, document.title, document.file_size)
    private = Path(settings.PRIVATE_STORAGE_ROOT)
    before_tree = (
        private.exists(),
        sorted(str(p.relative_to(private)) for p in private.rglob("*")),
    )
    dry = transfer_revision(revision.pk)
    assert dry["status"] == "ready" and dry["public_present"] and not dry["private_present"]
    assert (
        private.exists(),
        sorted(str(p.relative_to(private)) for p in private.rglob("*")),
    ) == before_tree
    assert not DocumentAudit.objects.filter(action=ACTION).exists()
    result = transfer_revision(revision.pk, apply=True, maintenance=True)
    assert result["status"] == "migrated" and not result["public_present"]
    assert not (Path(settings.MEDIA_ROOT) / old).exists()
    assert (Path(settings.PRIVATE_STORAGE_ROOT) / result["new_name"]).read_bytes() == DATA
    assert (Path(settings.PRIVATE_STORAGE_ROOT) / result["retired_name"]).read_bytes() == DATA
    document.refresh_from_db()
    assert document.document.name == result["new_name"]
    assert (
        document.created_at,
        document.updated_at,
        document.title,
        document.file_size,
    ) == metadata
    assert frozen(revision) == before
    assert document.document.url == f"/api/v1/elaborati/revisions/{revision.pk}/pdf"
    again = transfer_revision(revision.pk, apply=True, maintenance=True)
    assert again["status"] == "migrated"
    assert DocumentAudit.objects.filter(revision=revision, action=ACTION).count() == 1
    assert DocumentAudit.objects.filter(revision=revision, action=RETIRED_ACTION).count() == 1


def test_post_commit_interruption_resumes_from_audit_without_new_revision(
    site, settings, monkeypatch
):
    revision, document, old = issued(site, settings, legacy=True)
    original = PublicationTransfer.retire
    monkeypatch.setattr(
        PublicationTransfer, "retire", lambda *a: (_ for _ in ()).throw(OSError("EXDEV"))
    )
    first = transfer_revision(revision.pk, apply=True, maintenance=True)
    assert first["status"] == "retirement_pending"
    document.refresh_from_db()
    assert document.document.name == first["new_name"]
    assert (Path(settings.MEDIA_ROOT) / old).read_bytes() == DATA
    assert (Path(settings.PRIVATE_STORAGE_ROOT) / first["new_name"]).read_bytes() == DATA
    assert DocumentAudit.objects.filter(revision=revision, action=ACTION).count() == 1
    monkeypatch.setattr(PublicationTransfer, "retire", original)
    second = transfer_revision(revision.pk, apply=True, maintenance=True)
    assert second["status"] == "migrated" and second["old_name"] == old


def test_rollback_after_copy_can_resume_without_overwriting(site, settings, monkeypatch):
    revision, document, old = issued(site, settings, legacy=True)
    original = DocumentAudit.objects.create
    monkeypatch.setattr(
        DocumentAudit.objects,
        "create",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("DB rollback")),
    )
    with pytest.raises(RuntimeError, match="DB rollback"):
        transfer_revision(revision.pk, apply=True, maintenance=True)
    document.refresh_from_db()
    assert document.document.name == old and (Path(settings.MEDIA_ROOT) / old).exists()
    assert not DocumentAudit.objects.filter(action=ACTION).exists()
    monkeypatch.setattr(DocumentAudit.objects, "create", original)
    assert transfer_revision(revision.pk, apply=True, maintenance=True)["status"] == "migrated"


@pytest.mark.parametrize(
    "failure",
    ["hash", "size", "missing", "private_collision", "shared_document", "shared_attachment"],
)
def test_invalid_or_shared_source_is_blocked_without_renaming(site, settings, failure):
    revision, document, old = issued(site, settings, legacy=True)
    if failure == "hash":
        (Path(settings.MEDIA_ROOT) / old).write_bytes(b"changed")
    elif failure == "size":
        ProjectDocument.objects.filter(pk=document.pk).update(file_size=1)
    elif failure == "missing":
        (Path(settings.MEDIA_ROOT) / old).rename(Path(settings.MEDIA_ROOT) / "retained-fixture.pdf")
    elif failure == "private_collision":
        target = (
            Path(settings.PRIVATE_STORAGE_ROOT)
            / f"elaborati/publications/{revision.pk.hex}-{document.pk:032x}.pdf"
        )
        target.parent.mkdir(parents=True)
        target.write_bytes(b"must not overwrite")
    elif failure == "shared_document":
        ProjectDocument.objects.create(project=site[0], document=old, title="Shared file")
    else:
        PostAttachment.objects.create(post=site[4], file=old)
    result = transfer_revision(revision.pk, apply=True, maintenance=True)
    assert result["status"] == "blocked"
    assert not DocumentAudit.objects.filter(action=ACTION).exists()
    document.refresh_from_db()
    assert document.document.name == old


def test_command_requires_maintenance_and_reports_json(site, settings):
    revision, _, _ = issued(site, settings)
    with pytest.raises(CommandError, match="maintenance"):
        call_command("privatize_elaborati", apply=True)
    output = StringIO()
    call_command("privatize_elaborati", revision=revision.pk, stdout=output)
    import json

    assert json.loads(output.getvalue())["entries"][0]["status"] == "ready"
