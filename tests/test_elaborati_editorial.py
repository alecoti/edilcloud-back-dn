from copy import deepcopy
from types import SimpleNamespace
import uuid

import pytest
from pydantic import ValidationError

from edilcloud.modules.elaborati.content import (
    Composition,
    editor_from_composition,
    editor_claims,
    local_quality,
    validate_editor,
)
from edilcloud.modules.elaborati.editorial import BRIEFS, editorial_contract
from edilcloud.modules.elaborati.engine import check_source_ids
from edilcloud.modules.elaborati.jobs import process_job
from edilcloud.modules.elaborati.provider import strict_response_schema
from edilcloud.modules.elaborati.registry import template_for
from edilcloud.modules.elaborati.renderer import render_html
from edilcloud.modules.elaborati.schemas import ActionRequest, SaveRequest
from edilcloud.modules.elaborati import services
from tests import test_elaborati as baseline

site = baseline.site
provider = baseline.provider
pytestmark = pytest.mark.django_db


def composition(template, source_id):
    def claim(text):
        return {"text": text, "source_ids": [source_id], "nature": "reported"}

    return Composition(
        title="Rilievi B203",
        sections=[
            {
                "key": section["key"],
                "paragraphs": [claim(f"{section['label']}: verifica proposta nel locale B203.")],
                "lists": [
                    {
                        "style": "ordered",
                        "items": [claim("Verifica proposta del passaggio nel locale B203.")],
                    }
                ]
                if index == 0
                else [],
                "tables": [
                    {
                        "columns": ["Locale", "Riscontro"],
                        "rows": [[claim("B203"), claim("Verifica proposta")]],
                    }
                ]
                if index == 0
                else [],
            }
            for index, section in enumerate(template["sections"])
        ],
        photographs=[],
    )


@pytest.mark.parametrize("document_type", list(BRIEFS))
@pytest.mark.parametrize("language", ["it", "en", "fr", "ro", "ru", "ar"])
def test_editorial_contract_matches_every_template_without_changing_frozen_sections(
    document_type, language
):
    template = template_for(document_type, language)
    before = deepcopy(template)
    revision = SimpleNamespace(
        template_snapshot=template, elaborato=SimpleNamespace(document_type=document_type)
    )
    contract = editorial_contract(revision)
    assert [s["key"] for s in contract["sections"]] == [s["key"] for s in template["sections"]]
    assert all(s["purpose"] for s in contract["sections"])
    assert contract["version"] == "2026.10.7" and template == before


def test_editor_review_checks_operational_concepts_without_forbidding_merged_columns():
    revision = SimpleNamespace(
        template_snapshot=template_for("periodic_report"),
        elaborato=SimpleNamespace(document_type="periodic_report"),
    )
    writing = editorial_contract(revision)
    reviewing = editorial_contract(revision, for_review=True)
    assert "required_tables" in writing["document_structure"]
    assert "required_tables" not in reviewing["document_structure"]
    assert "table_contract" not in reviewing["document_structure"]
    register = reviewing["document_structure"]["operational_registers"]["section_4"][0]
    assert len(register["concepts"]) == 4 and "columns" not in register
    assert "blocking" in reviewing["document_structure"]["table_review"]
    assert reviewing["sections"] == writing["sections"]


def test_lists_tables_and_supported_novel_formatting_keep_cell_provenance_in_pdf(site, provider):
    revision = baseline.generate(site)
    source = next(s["id"] for s in revision.evidence["sources"] if s["kind"] == "post")
    document = editor_from_composition(
        composition(revision.template_snapshot, source), revision.template_snapshot
    )
    paragraph = document["content"][1]
    paragraph["attrs"]["textAlign"] = "right"
    paragraph["content"][0]["marks"] = [
        {"type": "underline"},
        {"type": "highlight", "attrs": {"color": None}},
        {
            "type": "link",
            "attrs": {
                "href": "https://example.test/tavola?x=1&y=2",
                "target": "_blank",
                "rel": "noopener noreferrer",
                "class": None,
            },
        },
    ]
    listing = next(n for n in document["content"] if n["type"] == "orderedList")
    listing["attrs"] = {"start": 3}
    saved = services.save_revision(
        profile=site[1],
        revision_id=revision.pk,
        payload=SaveRequest(version=revision.version, editor_doc=document),
    )
    markup = render_html(revision=saved, profile=site[1])
    assert (
        '<ol start="3">' in markup
        and "<thead>" in markup
        and "<u>" in markup
        and "<mark>" in markup
    )
    assert (
        "text-align:right" in markup
        and "x=1&amp;y=2" in markup
        and 'rel="noopener noreferrer"' in markup
    )
    assert saved.editor_doc == document
    assert any(c["text"] == "B203" and c["source_ids"] == [source] for c in editor_claims(document))
    assert not any(c["text"] in {"Locale", "Riscontro"} for c in editor_claims(document))


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "data:text/html,hello",
        "//example.test",
        "https://user:password@example.test",
        "https://example.test/\nredirect",
    ],
)
def test_pasted_links_cannot_introduce_script_schemes_or_credentials(site, provider, href):
    revision = baseline.generate(site)
    doc = deepcopy(revision.editor_doc)
    doc["content"][1]["content"][0]["marks"] = [{"type": "link", "attrs": {"href": href}}]
    with pytest.raises(ValueError):
        validate_editor(doc, revision.evidence, revision.template_snapshot)


def test_invalid_attribute_types_produce_controlled_validation_errors(site, provider):
    revision = baseline.generate(site)
    for key, value in [("nature", []), ("nature", ""), ("textAlign", []), ("sourceIds", None)]:
        doc = deepcopy(revision.editor_doc)
        doc["content"][1]["attrs"][key] = value
        with pytest.raises(ValueError):
            validate_editor(doc, revision.evidence, revision.template_snapshot)


def test_repeated_filler_does_not_pass_as_a_complete_professional_document(site, provider):
    revision = baseline.generate(site)
    doc = deepcopy(revision.editor_doc)
    for node in doc["content"]:
        if (
            node["type"] == "paragraph"
            and node.get("content")
            and node["content"][0]["type"] == "text"
        ):
            node["content"][0]["text"] = (
                "È stata proposta una verifica del locale B203, ma nelle registrazioni non risulta ancora documentato alcun riscontro conclusivo."
            )
    issues = local_quality(doc, revision.evidence, revision.template_snapshot)
    assert any(i["severity"] == "blocking" and "ripetuto" in i["explanation"] for i in issues)


def test_selected_section_proposal_preserves_other_manual_tables_and_keeps_new_structured_blocks(
    site, provider, monkeypatch
):
    revision = baseline.generate(site)
    source = next(s["id"] for s in revision.evidence["sources"] if s["kind"] == "post")
    doc = deepcopy(revision.editor_doc)
    manual_table = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [
                            {
                                "type": "paragraph",
                                "attrs": {
                                    "sectionKey": "section_2",
                                    "sourceIds": [source],
                                    "nature": "reported",
                                },
                                "content": [
                                    {"type": "text", "text": "Appunto manuale da preservare"}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    doc["content"].insert(4, manual_table)
    revision = services.save_revision(
        profile=site[1],
        revision_id=revision.pk,
        payload=SaveRequest(version=revision.version, editor_doc=doc),
    )
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.engine.structured_response",
        lambda **kwargs: composition(revision.template_snapshot, source),
    )
    job = services.request_action(
        profile=site[1],
        revision_id=revision.pk,
        payload=ActionRequest(
            idempotency_key=uuid.uuid4(),
            version=revision.version,
            action="rewrite",
            section_key="section_1",
        ),
    )
    process_job(job.pk)
    job.refresh_from_db()
    revision.refresh_from_db()
    assert job.state == "completed" and revision.editor_doc == doc
    proposed = job.result["editor_doc"]["content"]
    assert manual_table in proposed
    assert any(n["type"] == "orderedList" for n in proposed)
    assert sum(n["type"] == "table" for n in proposed) == 2


def test_generated_cells_require_real_sources_and_tables_must_be_rectangular(site, provider):
    revision = baseline.generate(site)
    value = composition(revision.template_snapshot, "not-a-real-source")
    with pytest.raises(ValueError, match="fonte inesistente"):
        check_source_ids(
            [cell for row in value.sections[0].tables[0].rows for cell in row], revision.evidence
        )
    payload = value.model_dump()
    payload["sections"][0]["tables"][0]["rows"][0].pop()
    with pytest.raises(ValidationError):
        Composition.model_validate(payload)


def test_strict_response_schema_requires_defaulted_arrays_too():
    schema = strict_response_schema(Composition)
    section = schema["$defs"]["Section"]
    assert set(section["required"]) == set(section["properties"])
    assert {"tables", "lists"} <= set(section["required"])
    assert section["additionalProperties"] is False


def test_pdf_hides_duplicate_adjacent_subtitle_and_request_uuid_without_changing_editor(
    site, provider
):
    revision = baseline.generate(site)
    document = deepcopy(revision.editor_doc)
    duplicate = deepcopy(document["content"][0])
    duplicate["attrs"]["level"] = 3
    document["content"].insert(1, duplicate)
    request = next(s["id"] for s in revision.evidence["sources"] if s["kind"] == "request")
    document["content"][2]["attrs"]["sourceIds"].append(request)
    revision = services.save_revision(
        profile=site[1],
        revision_id=revision.pk,
        payload=SaveRequest(version=revision.version, editor_doc=document),
    )
    markup = render_html(revision=revision, profile=site[1])
    assert "<h3 " not in markup and request not in markup
    assert "Richiesta del redattore" in markup
    assert revision.editor_doc == document


def test_provider_table_variants_require_matching_columns_rows_and_widths():
    template = {"sections": [{"key": "section_1"}]}
    schema = strict_response_schema(Composition, template)
    variants = schema["$defs"]["ClaimTable"]["anyOf"]
    assert len(variants) == 5
    for count, variant in enumerate(variants, start=2):
        columns = variant["properties"]["columns"]
        cells = variant["properties"]["rows"]["items"]
        widths = variant["properties"]["widths"]["anyOf"]
        assert columns["minItems"] == columns["maxItems"] == count
        assert cells["minItems"] == cells["maxItems"] == count
        assert widths[0]["maxItems"] == 0
        assert widths[1]["minItems"] == widths[1]["maxItems"] == count
        assert variant["additionalProperties"] is False
        assert set(variant["required"]) == set(variant["properties"])
