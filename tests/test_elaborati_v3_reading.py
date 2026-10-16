from django.core.files.base import ContentFile
from django.utils import timezone
import pytest

from edilcloud.modules.elaborati.inventory import build_inventory
from edilcloud.modules.elaborati.models import DocumentEvidenceItem
from edilcloud.modules.elaborati.preflight import DocumentPath, DocumentPreflight
from edilcloud.modules.elaborati.source_reading import (
    add_parts, extract_local_source, finalize_root, text_parts,
)
from edilcloud.modules.projects.models import ProjectDocument
from tests import test_elaborati as baseline
from tests.test_elaborati_v3_inventory import inventory_job

site = baseline.site
pytestmark = pytest.mark.django_db


def test_preflight_is_deterministic_and_does_not_call_provider(site):
    job = inventory_job(site)
    with pytest.raises(ValueError, match="inventario"):
        DocumentPreflight.inspect(job)
    build_inventory(job)
    assert DocumentPreflight.inspect(job).path == DocumentPath.FAST_1
    site[-1].alert = True
    site[-1].save()
    # Snapshot is stable; a new request is required to inspect changed sources.
    assert DocumentPreflight.inspect(job).path == DocumentPath.FAST_1
    root = job.evidence_items.get(source_id=f"post:{site[-1].pk}")
    root.payload["data"]["alert"] = True
    root.save()
    assert DocumentPreflight.inspect(job).path == DocumentPath.STANDARD


def test_preflight_empty_and_complex_paths(site):
    site[-1].delete()
    job = inventory_job(site)
    build_inventory(job)
    assert DocumentPreflight.inspect(job).path == DocumentPath.FAST_0
    item = job.evidence_items.first()
    for index in range(41):
        DocumentEvidenceItem.objects.create(job=job, source_id=f"post:fixture-{index}", kind="post",
                                            source_hash=str(index), payload={"data": {"text": "Fatto"}})
    assert DocumentPreflight.inspect(job).path == DocumentPath.DEEP
    assert item.job_id == job.pk


def test_long_text_segmentation_is_lossless_and_idempotent(site):
    job = inventory_job(site)
    build_inventory(job)
    item = job.evidence_items.get(source_id=f"post:{site[-1].pk}")
    value = ("Riga con un fatto e una condizione.\n" * 9000) + "Esito finale da conservare."
    assert "".join(text for _, _, text in text_parts(value)) == value
    first = add_parts(item, value)
    assert first == add_parts(item, value)
    assert len(first) > 8
    assert job.evidence_items.filter(parent_source_id=item.source_id).count() == len(first)


def test_pdf_reads_all_pages_after_page_eight_and_keeps_provenance(site):
    import pypdfium2 as pdfium

    # Actual PDF text extraction, no mock and no AI.
    pdf = pdfium.PdfDocument.new()
    for _ in range(12):
        pdf.new_page(100, 100)
    import io
    raw = io.BytesIO()
    pdf.save(raw)
    pdf.close()
    file = ProjectDocument.objects.create(project=site[0], title="Dodici pagine",
                                          document=ContentFile(raw.getvalue(), name="long.pdf"))
    job = inventory_job(site)
    build_inventory(job)
    item = job.evidence_items.get(source_id=f"document:{file.pk}")
    extract_local_source(job, item)
    # Empty pages are explicitly unreadable if no text/OCR result, not dropped.
    children = job.evidence_items.filter(parent_source_id=item.source_id)
    assert children.count() == 12
    assert set(children.values_list("payload__page", flat=True)) == set(range(1, 13))
    assert all(children.values_list("reason", flat=True))
    finalize_root(item)
    item.refresh_from_db()
    assert item.state == "unreadable" and item.reading["pages"] == 12
    assert job.steps.filter(kind="extraction", state="completed").count() == 12


def test_unsupported_file_and_extraction_error_are_explicit(site):
    file = ProjectDocument.objects.create(project=site[0], title="Sorgente non supportata",
                                          document=ContentFile(b"binary", name="model.rvt"))
    job = inventory_job(site)
    build_inventory(job)
    item = job.evidence_items.get(source_id=f"document:{file.pk}")
    extract_local_source(job, item)
    item.refresh_from_db()
    assert item.state == "unreadable" and item.reason == "unsupported_file_format_requires_conversion"
    assert item.read_at <= timezone.now()
