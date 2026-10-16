"""Real PostgreSQL fences and concurrent provider lanes, with no billable API."""
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier, Lock
import time

from django.db import connection
import httpx
import pytest

from edilcloud.modules.elaborati.checkpoints import run_step, threaded_step
from edilcloud.modules.elaborati.content import ReasoningResult
from edilcloud.modules.elaborati.intelligence_readers import parallel_map
from edilcloud.modules.elaborati.jobs import process_job
from edilcloud.modules.elaborati.provider import structured_response
from tests import test_elaborati as baseline
from tests.test_elaborati_v3_inventory import inventory_job

site = baseline.site
pytestmark = pytest.mark.django_db(transaction=True)


def require_postgres():
    if connection.vendor != "postgresql":
        pytest.skip("PostgreSQL concurrency acceptance requires PostgreSQL")


def test_two_specialists_overlap_and_keep_separate_step_attempt_usage_ledgers(site, settings, monkeypatch):
    require_postgres()
    job = inventory_job(site)
    settings.OPENAI_API_KEY = "synthetic-concurrency-key"
    settings.ELABORATI_V3_CONCURRENCY = 2
    barrier, lock = Barrier(2, timeout=20), Lock()
    active = maximum = 0

    def reply(request):
        nonlocal active, maximum
        index = json.loads(json.loads(request.content)["input"])["partition"]
        with lock:
            active += 1
            maximum = max(maximum, active)
        barrier.wait()
        with lock:
            active -= 1
        return httpx.Response(200, json={"id": f"concurrent-{index}", "status": "completed",
            "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                "facts": [], "duplicates": [], "contradictions": [], "missing_data": [],
            })}]}]})

    original = httpx.Client
    monkeypatch.setattr("edilcloud.modules.elaborati.provider.httpx.Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(reply)))

    def reader(index):
        return run_step(job=job, key=f"reader:{index}", kind="read", data={"partition": index}, schema=ReasoningResult,
            execute=lambda step: structured_response(job=job, stage="document_reading", schema=ReasoningResult,
                                                     instructions="QA", data={"partition": index}))

    assert len(list(parallel_map(reader, [1, 2]))) == 2
    assert maximum == 2
    assert job.steps.filter(state="completed").count() == 2
    assert job.steps.filter(attempts__state="completed").count() == 2
    assert set(job.usage.values_list("response_id", flat=True)) == {"concurrent-1", "concurrent-2"}
    job.refresh_from_db()
    assert job.consumed_tokens == 60


def test_duplicate_job_delivery_has_only_one_winning_worker(site, monkeypatch):
    require_postgres()
    revision = baseline.create(site)
    job = revision.jobs.get()
    calls = []

    def generate(current):
        calls.append(current.pk)
        time.sleep(0.2)
        return {"editor_doc": {"type": "doc", "content": []}, "evidence": {"sources": []},
                "reasoning": {}, "quality": {"passed": False}}

    monkeypatch.setattr("edilcloud.modules.elaborati.engine.generate_document", generate)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: threaded_step(lambda: process_job(job.pk)), [1, 2]))
    assert sorted(results) == [False, True]
    assert calls == [job.pk]
    job.refresh_from_db()
    assert job.state == "completed" and not job.usage.exists()


def test_parallel_duplicate_images_share_one_analysis_but_both_keep_outcomes(site, monkeypatch):
    require_postgres()
    from io import BytesIO
    from PIL import Image
    from django.core.cache import cache
    from django.core.files.base import ContentFile
    from edilcloud.modules.elaborati.inventory import build_inventory
    from edilcloud.modules.elaborati.intelligence_contracts import ImageDescription
    from edilcloud.modules.elaborati.intelligence_media import prepare_source
    from edilcloud.modules.projects.models import PostAttachment

    cache.clear()
    raw = BytesIO()
    Image.new("RGB", (30, 30), "white").save(raw, "PNG")
    for number in (1, 2):
        PostAttachment.objects.create(post=site[-1], file=ContentFile(raw.getvalue(), name=f"duplicate{number}.png"))
    job = inventory_job(site)
    build_inventory(job)
    images = list(job.evidence_items.filter(kind="image_attachment"))
    assert len(images) == 2
    calls = []

    def analyze(**kwargs):
        calls.append(kwargs["key"])
        time.sleep(0.2)
        return ImageDescription(description="Immagine bianca di prova", limitations="Nessun dettaglio tecnico", is_document=False)

    monkeypatch.setattr("edilcloud.modules.elaborati.intelligence_media.specialist", analyze)
    list(parallel_map(lambda item: prepare_source(job, item), images, workers=2))
    assert len(calls) == 1
    assert job.evidence_items.filter(kind="source_part").count() == 2
    for item in images:
        item.refresh_from_db()
        assert item.reading["visual_analysis"]["description"] == "Immagine bianca di prova"
