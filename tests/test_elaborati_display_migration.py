"""The two runners adopt one cache; incompatible schemas are never repaired silently."""

from datetime import timedelta
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from edilcloud.modules.elaborati.models import DraftPdfCache
from edilcloud.modules.elaborati.storage import private_document_storage
from tests import test_elaborati as baseline

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.skipif(connection.vendor != "postgresql", reason="PostgreSQL shared migration"),
]
from tests.test_elaborati import site, provider  # shared fixtures
SQL = (
    Path(__file__).resolve().parents[1]
    / "src/edilcloud/modules/elaborati/migrations/0012_shared_display_cache.sql"
).read_text()


def artifact(site, revision):
    name = private_document_storage().save(
        f"elaborati/previews/{revision.pk}.pdf", ContentFile(b"%PDF-synthetic-migration")
    )
    return DraftPdfCache.objects.create(
        revision=revision,
        profile=site[1],
        content_hash="c" * 64,
        pdf_file=name,
        pdf_hash="a" * 64,
        created_at=timezone.now(),
    )


def execute_native_resource():
    resource = (
        Path(__file__).resolve().parents[2]
        / "rust/resources/migrations/2026102601_shared_elaborati_pdf_cache.sql"
    )
    if resource.exists():
        assert resource.read_text() == SQL
    with connection.cursor() as cursor:
        cursor.execute(SQL)


def test_native_first_then_django_adopts_and_rollback_preserves_shared_bytes(site):
    MigrationExecutor(connection).migrate([("elaborati", "0011_document_author_snapshot")])
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE public.elaborati_draftpdfcache")
    execute_native_resource()
    entry = artifact(site, baseline.create(site))
    MigrationExecutor(connection).migrate([("elaborati", "0012_shared_display_cache")])
    assert DraftPdfCache.objects.get(pk=entry.pk).pdf_file == entry.pdf_file
    MigrationExecutor(connection).migrate([("elaborati", "0011_document_author_snapshot")])
    assert DraftPdfCache.objects.get(pk=entry.pk).pdf_file == entry.pdf_file
    MigrationExecutor(connection).migrate([("elaborati", "0012_shared_display_cache")])
    assert private_document_storage().open(entry.pdf_file).read() == b"%PDF-synthetic-migration"


def test_django_first_then_native_preserves_newer_cache_and_imports_legacy(site):
    current = artifact(site, baseline.create(site))
    legacy_revision = baseline.create(site)
    legacy_path = private_document_storage().save(
        f"elaborati/previews/{legacy_revision.pk}.pdf", ContentFile(b"%PDF-legacy-synthetic")
    )
    with connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA edilcloud_runtime")
        cursor.execute(
            "CREATE TABLE edilcloud_runtime.elaborati_draft_pdf_cache (LIKE public.elaborati_draftpdfcache INCLUDING ALL)"
        )
        cursor.execute(
            "INSERT INTO edilcloud_runtime.elaborati_draft_pdf_cache VALUES (%s,%s,%s,%s,%s,%s)",
            [
                current.revision_id,
                current.profile_id,
                "d" * 64,
                "elaborati/previews/older.pdf",
                "b" * 64,
                current.created_at - timedelta(days=1),
            ],
        )
        cursor.execute(
            "INSERT INTO edilcloud_runtime.elaborati_draft_pdf_cache VALUES (%s,%s,%s,%s,%s,%s)",
            [
                legacy_revision.pk,
                current.profile_id,
                "e" * 64,
                legacy_path,
                "f" * 64,
                timezone.now(),
            ],
        )
    execute_native_resource()
    execute_native_resource()
    assert DraftPdfCache.objects.get(pk=current.pk).pdf_file == current.pdf_file
    assert (
        DraftPdfCache.objects.get(revision=legacy_revision, profile=site[1]).pdf_file == legacy_path
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM edilcloud_runtime.elaborati_draft_pdf_cache")
        assert cursor.fetchone()[0] == 0
    assert private_document_storage().exists(legacy_path)
    assert private_document_storage().exists(current.pdf_file)


def test_incompatible_cache_is_rejected_without_losing_existing_artifacts(site):
    with connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE public.elaborati_draftpdfcache ALTER COLUMN pdf_hash DROP NOT NULL"
        )
    entry = artifact(site, baseline.create(site))
    with pytest.raises(
        DatabaseError, match="Incompatible shared Elaborati PDF cache column pdf_hash"
    ):
        with transaction.atomic():
            execute_native_resource()
    assert DraftPdfCache.objects.get(pk=entry.pk).pdf_file == entry.pdf_file
    assert private_document_storage().exists(entry.pdf_file)
