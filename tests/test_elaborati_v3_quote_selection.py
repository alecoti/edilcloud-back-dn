"""A bad literal quote needs bounded selection, not a second paid reader."""
from copy import deepcopy
import json

import httpx
import pytest

from edilcloud.modules.elaborati.intelligence_contracts import ReaderResult
from edilcloud.modules.elaborati.intelligence_readers import validate_reader_with_quote_repair
from tests import test_elaborati as baseline
from tests.test_elaborati_v3_inventory import inventory_job

site = baseline.site
pytestmark = pytest.mark.django_db


def inputs():
    part = {"part_id": "part:member", "source_id": "member:25", "origin_kind": "member", "page": None,
            "text": '{"name":"Sofia Mancini","role":"d","professional_roles":["lavoratore"]}'}
    result = ReaderResult.model_validate({"facts": [{"id": "f1", "text": "Sofia Mancini ha ruolo w.",
        "nature": "declared", "category": "person", "event_date": "", "author": "",
        "critical": False, "relevant": True, "relevance_reason": "Anagrafica",
        "references": [{"part_id": part["part_id"], "source_id": part["source_id"], "page": None,
                        "quote": '"name":"Sofia Mancini","role":"w"'}]}],
        "sources": [{"part_id": part["part_id"], "status": "read", "reason": "Esaminata"}]})
    return part, result


def provider(settings, monkeypatch, quotes):
    settings.OPENAI_API_KEY = "synthetic-quote-selection-key"
    calls = []

    def reply(request):
        body = json.loads(request.content)
        assert body["reasoning"]["effort"] == "medium" and "max_output_tokens" not in body
        calls.append(body)
        return httpx.Response(200, json={"id": "quote-selection-one", "status": "completed",
            "usage": {"input_tokens": 30, "output_tokens": 20, "total_tokens": 50},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                "references": [{"reference_key": "f1:0", "quotes": quotes}]})}]}]})

    original = httpx.Client
    monkeypatch.setattr("edilcloud.modules.elaborati.provider.httpx.Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(reply)))
    return calls


def test_exact_quote_selection_is_cached_and_never_silently_changes_false_fact(site, settings, monkeypatch):
    job = inventory_job(site)
    part, result = inputs()
    original = result.model_copy(deep=True)
    quote = '"name":"Sofia Mancini","role":"d"'
    calls = provider(settings, monkeypatch, [quote])
    for _ in range(2):
        selected = validate_reader_with_quote_repair(job, result.model_copy(deep=True), [part], "batch-one")
        assert selected.facts[0].references[0].quote == quote
        assert selected.facts[0].text == original.facts[0].text, "A real passage must not silently validate or rewrite a false claim"
        assert selected.facts[0].nature == original.facts[0].nature
    assert len(calls) == 1 and job.usage.get().total_tokens == 50
    assert result == original


@pytest.mark.parametrize("quotes", [[], ['"role":"w"']])
def test_unrepairable_quote_is_not_accepted_and_does_not_start_a_retry_loop(site, settings, monkeypatch, quotes):
    job = inventory_job(site)
    part, result = inputs()
    calls = provider(settings, monkeypatch, quotes)
    for _ in range(2):
        with pytest.raises(ValueError, match="nessun ulteriore tentativo"):
            validate_reader_with_quote_repair(job, deepcopy(result), [part], "batch-one")
    assert len(calls) == 1 and job.usage.get().total_tokens == 50


def test_fast_route_cannot_claim_single_call_when_quote_selection_was_needed():
    from edilcloud.modules.elaborati.preflight import fast_review_reason

    assert fast_review_reason([], {"literal_quote_selection": True, "issues": []}) == "quote_selection_requires_independent_review"


def test_terminal_quote_failure_does_not_offer_a_useless_resume(site, settings, monkeypatch):
    from edilcloud.modules.elaborati import services
    from edilcloud.modules.elaborati.errors import UnusableDocumentResult
    from edilcloud.modules.elaborati.jobs import process_job
    from tests.test_elaborati_v3_pipeline import create_v3

    revision = create_v3(site, settings)
    job = revision.jobs.get()

    def invalid(job):
        raise UnusableDocumentResult("Citazione non verificabile dopo la selezione.")

    monkeypatch.setattr("edilcloud.modules.elaborati.pipeline_v3.generate_document", invalid)
    process_job(job.pk)
    job.refresh_from_db()
    assert job.state == "failed" and job.error_code == "DOCUMENT_RESULT_INVALID"
    assert not services.job_resumable(job)
    assert not services.serialize_job(job, include_thinking=True)["can_resume"]
