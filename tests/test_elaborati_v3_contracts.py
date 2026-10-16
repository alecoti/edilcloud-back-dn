import json

import httpx
import pytest

from edilcloud.modules.elaborati.content import Composition
from edilcloud.modules.elaborati.document_structure import registers_for
from edilcloud.modules.elaborati.intelligence_contracts import FastDocumentResult
from edilcloud.modules.elaborati.provider import strict_response_schema, structured_response
from edilcloud.modules.elaborati.registry import TYPES, template_for
from tests import test_elaborati as baseline
from tests.test_elaborati_v3_inventory import inventory_job

site = baseline.site


@pytest.mark.parametrize("document_type", TYPES)
def test_fast_contract_preserves_frozen_sections_required_registers_and_photo_constraints(document_type):
    template = template_for(document_type)
    evidence = {"sources": [{"id": "post:1", "kind": "post"}]}
    fast = strict_response_schema(FastDocumentResult, template, evidence)
    regular = strict_response_schema(Composition, template, evidence)
    assert fast["$defs"]["Composition"]["properties"] == regular["properties"]
    assert fast["$defs"]["Composition"]["required"] == regular["required"]
    assert fast["$defs"]["Claim"]["properties"]["parts"] == regular["$defs"]["Claim"]["properties"]["parts"]
    assert "maxItems" not in fast["$defs"]["Claim"]["properties"]["fact_ids"]
    assert regular["$defs"]["Claim"]["properties"]["fact_ids"]["maxItems"] == 0
    assert fast["$defs"]["Composition"]["properties"]["photographs"]["maxItems"] == 0
    assert "factual_review" not in fast["properties"]


@pytest.mark.django_db
def test_fast_provider_decodes_structured_parts_and_required_registers_in_one_response(site, settings, monkeypatch):
    job = inventory_job(site)
    settings.OPENAI_API_KEY = "synthetic-test-key"
    template = job.revision.template_snapshot
    claim = {"parts": [{"text": "Informazione da completare."}], "nature": "unverified", "source_ids": []}
    sections = {}
    for section in template["sections"]:
        value = {"paragraphs": [claim], "lists": [], "tables": [], "layout": []}
        definitions = registers_for(template).get(section["key"], [])
        if definitions:
            value["required_tables"] = {
                r["key"]: {"rows": [{column: {"paragraphs": [claim]} for column in r["columns"]}]}
                for r in definitions
            }
        sections[section["key"]] = value
    result = {"reading": {"facts": [], "sources": []}, "plan": {"allocations": [], "requirements": []},
              "composition": {"title": "QA", "subtitle": "", "sections": sections, "photographs": []}}
    calls = []

    def reply(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"id": "nested-composition-qa", "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(result)}]}]})

    original = httpx.Client
    monkeypatch.setattr("edilcloud.modules.elaborati.provider.httpx.Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(reply)))
    value = structured_response(job=job, stage="document_fast", schema=FastDocumentResult, effort="medium",
                                instructions="QA", data={"template": template, "evidence": {"sources": []}})
    assert len(calls) == 1 and "max_output_tokens" not in calls[0]
    assert calls[0]["reasoning"]["effort"] == "medium"
    assert [section.key for section in value.composition.sections] == [s["key"] for s in template["sections"]]
    assert sum(len(s.tables) for s in value.composition.sections) == sum(len(r) for r in registers_for(template).values())
