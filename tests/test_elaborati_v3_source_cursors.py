"""Provider work must not retain database read cursors across heartbeats."""
from concurrent.futures import ThreadPoolExecutor

from django.db import close_old_connections
import pytest

from edilcloud.modules.elaborati.intelligence_readers import evidence_records
from edilcloud.modules.elaborati.models import DocumentEvidenceItem, DocumentJob
from tests import test_elaborati as baseline
from tests.test_elaborati_v3_inventory import inventory_job

site = baseline.site
pytestmark = pytest.mark.django_db(transaction=True)


def test_source_pages_release_cursor_before_provider_heartbeat_and_keep_all_changed_rows(site):
    job = inventory_job(site)
    for index in range(113):
        DocumentEvidenceItem.objects.create(job=job, source_id=f"post:{index:04}", kind="post",
                                           source_hash=str(index), payload={}, parent_source_id=f"group:{index % 3}")
    selected = job.evidence_items.filter(state="pending")
    expected = list(selected.order_by("parent_source_id", "source_id").values_list("pk", flat=True))
    visited = []

    def heartbeat():
        close_old_connections()
        try:
            return DocumentJob.objects.filter(pk=job.pk).update(stage="heartbeat")
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as executor:
        for item in evidence_records(selected, page_size=7, order=("parent_source_id", "source_id")):
            assert executor.submit(heartbeat).result(timeout=5) == 1
            visited.append(item.pk)
            # Selection changes between pages: offset pagination would skip
            # rows, and a retained read cursor would block the other writer.
            DocumentEvidenceItem.objects.filter(pk=item.pk).update(state="read", reason="examined")
    assert visited == expected and not selected.exists()
