"""Storage placement only; legacy retirement and end-to-end rollout are separate."""

import uuid
import os
import subprocess
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from django.core.files.base import ContentFile

from edilcloud.modules.projects.document_storage import ProjectDocumentStorage
from edilcloud.modules.elaborati import maintenance
from tests import test_elaborati as baseline

site = baseline.site


def name():
    revision = uuid.uuid4()
    return revision, f"elaborati/publications/{revision.hex}-{uuid.uuid4().hex}.pdf"


def test_publication_copy_is_private_but_keeps_logical_name_size_and_authenticated_url(
    settings, tmp_path
):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_STORAGE_ROOT = tmp_path / "private"
    storage = ProjectDocumentStorage()
    revision, logical = name()
    data = b"%PDF synthetic storage fixture"
    assert storage.save(logical, ContentFile(data)) == logical
    assert not (Path(settings.MEDIA_ROOT) / logical).exists()
    assert (Path(settings.PRIVATE_STORAGE_ROOT) / logical).read_bytes() == data
    assert storage.size(logical) == len(data)
    assert storage.url(logical) == f"/api/v1/elaborati/revisions/{revision}/pdf"
    assert (
        storage.save("projects/1/documents/ordinary.txt", ContentFile(b"ordinary"))
        == "projects/1/documents/ordinary.txt"
    )
    assert (
        Path(settings.MEDIA_ROOT) / "projects/1/documents/ordinary.txt"
    ).read_bytes() == b"ordinary"
    assert (
        storage.url("projects/1/documents/ordinary.txt")
        == "/media/projects/1/documents/ordinary.txt"
    )


def test_missing_private_copy_never_falls_back_to_a_public_copy(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_STORAGE_ROOT = tmp_path / "private"
    storage = ProjectDocumentStorage()
    _, logical = name()
    public = Path(settings.MEDIA_ROOT) / logical
    public.parent.mkdir(parents=True)
    public.write_bytes(b"public legacy bytes")
    assert not storage.exists(logical)
    with pytest.raises(FileNotFoundError):
        storage.open(logical)
    assert public.read_bytes() == b"public legacy bytes"
    with pytest.raises(ValueError):
        storage.url("elaborati/publications/not-a-revision.pdf")


@pytest.mark.parametrize("placement", ["same", "nested", "private_parent"])
def test_publication_root_must_not_resolve_inside_media(settings, tmp_path, placement):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_STORAGE_ROOT = {
        "same": tmp_path / "media",
        "nested": tmp_path / "media/private",
        "private_parent": tmp_path,
    }[placement]
    if placement == "private_parent":
        settings.MEDIA_ROOT = tmp_path / "elaborati"
    with pytest.raises(ImproperlyConfigured):
        ProjectDocumentStorage().save(name()[1], ContentFile(b"preserve"))


@pytest.mark.django_db
def test_real_publication_metadata_and_maintenance_use_private_storage(site):
    storage = ProjectDocumentStorage()
    _, logical = name()
    storage.save(logical, ContentFile(b"%PDF storage fixture"))
    from edilcloud.modules.projects.models import ProjectDocument

    document = ProjectDocument.objects.create(
        project=site[0], uploaded_by=site[1], title="Private fixture", document=logical
    )
    assert document.file_size == len(b"%PDF storage fixture")
    assert document.document.storage.path(logical) == storage.path(logical)
    assert (
        maintenance.cleanup_publication_copies(dry_run=True) == []
    )  # Newly written, never old enough.
    document.refresh_from_db()
    with document.document.open("rb") as f:
        assert f.read() == b"%PDF storage fixture"


def test_private_publication_rejects_links(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.PRIVATE_STORAGE_ROOT = tmp_path / "private"
    outside = tmp_path / "outside"
    outside.mkdir()
    private = Path(settings.PRIVATE_STORAGE_ROOT)
    private.mkdir()
    try:
        (private / "elaborati").symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(private / "elaborati"), str(outside)],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    with pytest.raises(SuspiciousFileOperation):
        ProjectDocumentStorage().save(name()[1], ContentFile(b"secret"))
    assert list(outside.iterdir()) == []


def test_missing_private_root_below_public_alias_is_rejected(settings, tmp_path):
    public = tmp_path / "media"
    public.mkdir()
    settings.MEDIA_ROOT = public
    alias = tmp_path / "public-alias"
    try:
        alias.symlink_to(public, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(alias), str(public)],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    settings.PRIVATE_STORAGE_ROOT = alias / "not-yet-created"
    with pytest.raises(ImproperlyConfigured):
        ProjectDocumentStorage().save(name()[1], ContentFile(b"secret"))
    assert not (public / "not-yet-created").exists()
