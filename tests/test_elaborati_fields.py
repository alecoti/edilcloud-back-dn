"""Documentary completion must survive the real save/verify/render boundary."""

from copy import deepcopy
from pathlib import Path
from datetime import timedelta
import json
import uuid

import pytest

from edilcloud.modules.elaborati import services
from edilcloud.modules.elaborati.content import (
    Composition,
    editor_from_composition,
    editor_claims,
    local_quality,
    validate_editor,
)
from edilcloud.modules.elaborati.fields import fields_in, field_source_id, preserve_completed_fields
from edilcloud.modules.elaborati.registry import TYPES, template_for
from edilcloud.modules.elaborati.renderer import render_html, render_pdf
from edilcloud.modules.elaborati.schemas import SaveRequest, ActionRequest
from tests import test_elaborati as baseline

site = baseline.site
provider = baseline.provider
pytestmark = pytest.mark.django_db


def field(key="ordinary_hours", kind="hours", value="", person=""):
    return {
        "type": "documentField",
        "attrs": {
            "fieldId": key,
            "label": "Ore ordinarie" if kind == "hours" else "Referente da confermare",
            "kind": kind,
            "unit": "h" if kind == "hours" else "",
            "value": value,
            "personSourceId": person,
        },
    }


def paragraph(node, section="section_2"):
    return {
        "type": "paragraph",
        "attrs": {"sectionKey": section, "sourceIds": [], "nature": "unverified"},
        "content": [node],
    }


@pytest.mark.parametrize("kind", TYPES)
def test_each_document_type_has_typed_fields_inside_tables_not_invented_facts(kind):
    template = template_for(kind)
    sections = []
    for index, definition in enumerate(template["sections"]):
        sections.append(
            {
                "key": definition["key"],
                "paragraphs": [
                    {
                        "text": "Da integrare nella redazione.",
                        "source_ids": [],
                        "nature": "unverified",
                    }
                ],
                "tables": [
                    {
                        "columns": ["Persona", "Ore"],
                        "rows": [
                            [
                                {
                                    "text": f"{{{{person_{index}}}}}",
                                    "source_ids": [],
                                    "nature": "unverified",
                                    "fields": [
                                        {
                                            "key": f"person_{index}",
                                            "label": "Persona",
                                            "kind": "person",
                                        }
                                    ],
                                },
                                {
                                    "text": f"{{{{hours_{index}}}}}",
                                    "source_ids": [],
                                    "nature": "unverified",
                                    "fields": [
                                        {
                                            "key": f"hours_{index}",
                                            "label": "Ore",
                                            "kind": "hours",
                                            "unit": "h",
                                        }
                                    ],
                                },
                            ]
                        ],
                    }
                ],
            }
        )
    composition = Composition(
        title="Documento completo da compilare", sections=sections, photographs=[]
    )
    doc = editor_from_composition(composition, template)
    validate_editor(doc, {"sources": []}, template)
    assert len(list(fields_in(doc))) == 2 * len(sections)
    assert not any(
        issue["severity"] == "blocking" for issue in local_quality(doc, {"sources": []}, template)
    )


def test_completion_is_attributed_and_reused_without_reassigning_authorship(site, provider):
    revision = baseline.generate(site)
    doc = deepcopy(revision.editor_doc)
    doc["content"].insert(3, paragraph(field(value="8.5")))
    owner = site[1]
    saved = services.save_revision(
        profile=owner,
        revision_id=revision.pk,
        payload=SaveRequest(version=revision.version, editor_doc=doc),
    )
    declaration = next(d for d in saved.declarations if d.get("field_id") == "ordinary_hours")
    assert declaration["profile_id"] == owner.pk and declaration["author"] == "Laura Verdi"
    sid = field_source_id(next(fields_in(doc)))
    assert (
        next(s for s in saved.evidence["sources"] if s["id"] == sid)["data"]["document_field"][
            "value"
        ]
        == "8.5"
    )
    assert any(sid in c["source_ids"] for c in editor_claims(saved.editor_doc))
    assert not any(
        i["severity"] == "blocking"
        for i in local_quality(saved.editor_doc, saved.evidence, saved.template_snapshot)
    )
    markup = render_html(revision=saved, profile=owner)
    assert "8.5 h" in markup and "Ore ordinarie: 8.5 h" in markup
    again = services.save_revision(
        profile=owner,
        revision_id=saved.pk,
        payload=SaveRequest(version=saved.version, editor_doc=doc),
    )
    assert again.declarations == saved.declarations
    updated = deepcopy(doc)
    next(fields_in(updated))["value"] = "9"
    changed = services.save_revision(
        profile=owner,
        revision_id=again.pk,
        payload=SaveRequest(version=again.version, editor_doc=updated),
    )
    assert len(changed.declarations) == 1 and "9 h" in changed.declarations[0]["text"]
    next(fields_in(updated))["value"] = ""
    cleared = services.save_revision(
        profile=owner,
        revision_id=changed.pk,
        payload=SaveRequest(version=changed.version, editor_doc=updated),
    )
    assert not cleared.declarations and sid not in {s["id"] for s in cleared.evidence["sources"]}


def test_person_reference_is_a_project_tag_and_signature_cannot_be_forged(site, provider):
    revision = baseline.generate(site)
    member = next(s for s in revision.evidence["sources"] if s["kind"] == "member")
    doc = deepcopy(revision.editor_doc)
    node = field("referent", "person", member["data"]["name"], member["id"])
    doc["content"].insert(3, paragraph(node))
    validate_editor(doc, revision.evidence, revision.template_snapshot)
    node["attrs"]["personSourceId"] = "member:unrelated-project"
    with pytest.raises(ValueError, match="cantiere"):
        validate_editor(doc, revision.evidence, revision.template_snapshot)
    node["attrs"] = field("signature", "signature", "Fake signature")["attrs"]
    with pytest.raises(ValueError, match="firma"):
        validate_editor(doc, revision.evidence, revision.template_snapshot)


def test_final_pdf_preview_uses_publication_state_without_changing_the_draft(site, provider):
    revision = baseline.generate(site)
    markup = render_html(revision=revision, profile=site[1], publication_state="published")
    assert "· Pubblicato</span>" in markup
    assert revision.state == "draft"


def test_a_replaced_photo_cannot_silently_replace_the_evidence_used_by_the_editor(site, provider):
    import io
    from PIL import Image
    from django.core.files.base import ContentFile
    from edilcloud.modules.projects.models import PostAttachment
    from edilcloud.modules.elaborati.evidence import build_evidence, resolve_evidence_file

    data = io.BytesIO()
    Image.new("RGB", (20, 20), "green").save(data, "PNG")
    attachment = PostAttachment.objects.create(
        post=site[-1], file=ContentFile(data.getvalue(), name="before.png")
    )
    revision = baseline.create(site)
    bundle = build_evidence(profile=site[1], elaborato=revision.elaborato)
    source = next(s for s in bundle["sources"] if s.get("file_ref", {}).get("id") == attachment.pk)
    with resolve_evidence_file(profile=site[1], project_id=site[0].pk, source=source).open("rb") as frozen:
        assert frozen.read() == data.getvalue()
    replacement = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(replacement, "PNG")
    attachment.file.save("after.png", ContentFile(replacement.getvalue()))
    # The revision continues using the exact archived version, never today's file.
    with resolve_evidence_file(profile=site[1], project_id=site[0].pk, source=source).open("rb") as frozen:
        assert frozen.read() == data.getvalue()
    refreshed = build_evidence(profile=site[1], elaborato=revision.elaborato)
    current = next(s for s in refreshed["sources"] if s["id"] == source["id"])
    assert current["source_uuid"] == source["source_uuid"]
    assert current["file_sha256"] != source["file_sha256"]


def test_editor_roundtrip_allows_default_null_column_widths_without_breaking_pdf(site, provider):
    revision = baseline.generate(site)
    from tests.test_elaborati_editorial import composition

    source = next(s["id"] for s in revision.evidence["sources"] if s["kind"] == "post")
    revision.editor_doc = editor_from_composition(
        composition(revision.template_snapshot, source), revision.template_snapshot
    )
    table = next(n for n in revision.editor_doc["content"] if n["type"] == "table")
    for row in table["content"]:
        for cell in row["content"]:
            cell["attrs"] = {"colspan": 1, "rowspan": 1, "colwidth": None}
    markup = render_html(revision=revision, profile=site[1])
    assert "B203" in markup and "<thead>" in markup


def test_ordered_blocks_keep_photo_table_and_observation_together_without_losing_cells():
    from tests.test_elaborati_editorial import composition

    template = template_for("inspection")
    value = composition(template, "post:1")
    from edilcloud.modules.elaborati.content import BlockPlacement, Photograph, Claim

    value.photographs = [
        Photograph(
            source_id="photo:1",
            section_key="section_1",
            title="Rilievo B203",
            caption=Claim(
                text="Immagine associata al rilievo.", source_ids=["post:1"], nature="reported"
            ),
        )
    ]
    value.sections[0].layout = [
        BlockPlacement(kind="heading", label="Rilievo fotografico"),
        BlockPlacement(kind="photo", index=0),
        BlockPlacement(kind="paragraph", index=0),
        BlockPlacement(kind="table", index=0),
        BlockPlacement(kind="list", index=0),
    ]
    value.sections[0].tables[0].widths = [25, 75]
    doc = editor_from_composition(value, template)
    assert [n["type"] for n in doc["content"][:6]] == [
        "heading",
        "heading",
        "evidencePhoto",
        "paragraph",
        "table",
        "orderedList",
    ]
    table = doc["content"][4]
    assert [c["attrs"]["colwidth"] for c in table["content"][0]["content"]] == [[250], [750]]
    validate_editor(
        doc,
        {"sources": [{"id": "post:1", "kind": "post"}, {"id": "photo:1", "kind": "photo"}]},
        template,
    )
    assert any(c["text"] == "B203" for c in editor_claims(doc))
    value.sections[0].layout.pop()
    with pytest.raises(ValueError, match="omette"):
        editor_from_composition(value, template)


@pytest.mark.parametrize(
    "kind,value", [("hours", "-3"), ("quantity", "NaN"), ("date", "2026-02-30"), ("time", "29:00")]
)
def test_field_types_reject_ambiguous_or_invalid_values(kind, value):
    doc = {"type": "doc", "content": [paragraph(field(kind=kind, value=value))]}
    with pytest.raises(ValueError):
        validate_editor(doc, {"sources": []}, template_for("daily_report"))


def test_ai_edit_cannot_erase_or_overwrite_manual_completion():
    before = {"type": "doc", "content": [paragraph(field(value="8"))]}
    proposal = deepcopy(before)
    next(fields_in(proposal))["value"] = "99"
    assert next(fields_in(preserve_completed_fields(before, proposal)))["value"] == "8"
    with pytest.raises(ValueError, match="omette"):
        preserve_completed_fields(before, {"type": "doc", "content": []})


def test_missing_data_prose_around_an_editable_value_is_flagged_for_polishing():
    from edilcloud.modules.elaborati.fields import editable_context_issues

    claim = {
        "section_key": "section_2",
        "text": "Orario non documentato: [Ora inizio]",
        "document_fields": [field("start", "time")["attrs"]],
    }
    assert editable_context_issues([claim])[0]["category"] == "editable_context"
    claim["text"] = "Orario di inizio: [Ora inizio]"
    assert not editable_context_issues([claim])


def test_wire_parts_build_matching_placeholders_and_distinct_field_instances():
    from edilcloud.modules.elaborati.provider import strict_response_schema, decode_document_parts

    schema = strict_response_schema(Composition, template_for("daily_report"))
    claim = schema["$defs"]["Claim"]
    assert "parts" in claim["required"] and "text" not in claim["properties"]
    assert "fields" not in claim["properties"]
    locked = strict_response_schema(
        Composition,
        template_for("daily_report"),
        {
            "sources": [
                {"id": "post:1", "kind": "post"},
                {"id": "image_attachment:8", "kind": "image_attachment"},
            ]
        },
    )
    assert locked["$defs"]["EvidenceSourceId"]["enum"] == ["post:1", "image_attachment:8"]
    assert locked["$defs"]["Claim"]["properties"]["source_ids"]["items"] == {
        "$ref": "#/$defs/EvidenceSourceId"
    }
    assert locked["$defs"]["Photograph"]["properties"]["source_id"]["enum"] == [
        "image_attachment:8"
    ]
    no_photos = strict_response_schema(
        Composition, template_for("daily_report"), {"sources": [{"id": "post:1", "kind": "post"}]}
    )
    assert no_photos["properties"]["photographs"]["maxItems"] == 0
    value = {
        "source_ids": [],
        "nature": "unverified",
        "parts": [
            {"text": "Ore ordinarie: "},
            {"field": {"key": "hours", "label": "Ore ordinarie", "kind": "hours", "unit": "h"}},
            {"text": "; ore straordinarie: "},
            {"field": {"key": "hours", "label": "Ore straordinarie", "kind": "hours", "unit": "h"}},
        ],
    }
    result = decode_document_parts(value)
    from edilcloud.modules.elaborati.content import Claim

    validated = Claim.model_validate(result)
    assert validated.text == "Ore ordinarie: {{hours}}; ore straordinarie: {{hours.2}}"
    assert [field.key for field in validated.fields] == ["hours", "hours.2"]
    with pytest.raises(ValueError, match="esistente duplicato"):
        decode_document_parts(
            {
                "source_ids": [],
                "nature": "unverified",
                "parts": [
                    {"field": {"key": "hours", "label": "Ore", "kind": "hours", "unit": "h"}},
                    {"field": {"key": "hours", "label": "Ore", "kind": "hours", "unit": "h"}},
                ],
            },
            existing_field_ids=["hours"],
        )


@pytest.mark.parametrize("language", ["it", "en", "fr", "ro", "ru", "ar"])
def test_signature_space_is_editable_content_but_never_counts_as_a_fact(language):
    from edilcloud.modules.elaborati.fields import ensure_signature_slot

    template = template_for("inspection", language)
    doc = {"type": "doc", "content": []}
    ensure_signature_slot(doc, template, language)
    ensure_signature_slot(doc, template, language)
    assert len(list(fields_in(doc))) == 1
    assert not editor_claims(doc)
    assert any(i["severity"] == "blocking" for i in local_quality(doc, {"sources": []}, template))


def test_editor_defaults_preserve_review_but_content_changes_mark_review_stale(site, provider):
    revision = baseline.generate(site)
    original = deepcopy(revision.quality)
    doc = deepcopy(revision.editor_doc)
    for node in doc["content"]:
        if node["type"] in {"paragraph", "heading"}:
            node.setdefault("attrs", {})["textAlign"] = None
    saved = services.save_revision(
        profile=site[1],
        revision_id=revision.pk,
        payload=SaveRequest(version=revision.version, editor_doc=doc),
    )
    assert saved.quality["passed"] and saved.quality["checked_at"] == original["checked_at"]
    from edilcloud.modules.elaborati.content import digest

    # Harmless defaults are a no-op: keep the saved canonical JSON and version.
    assert saved.version == revision.version
    assert saved.quality["content_hash"] == digest(saved.editor_doc)
    assert saved.quality["evidence_hash"] == saved.evidence["bundle_hash"]
    proposal = deepcopy(doc)
    proposal["content"][1]["content"][0]["text"] += " Chiusura dichiarata."
    changed = services.save_revision(
        profile=site[1],
        revision_id=saved.pk,
        payload=SaveRequest(version=saved.version, editor_doc=proposal),
    )
    assert not changed.quality["passed"] and changed.quality["needs_verification"]


def test_preview_uses_no_ai_while_explicit_verify_still_calls_provider(site, provider, monkeypatch):
    from edilcloud.modules.elaborati.jobs import process_job

    revision = baseline.generate(site)
    calls_before = len(provider)
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-no-ai"
    )
    preview = services.request_action(
        profile=site[1],
        revision_id=revision.pk,
        payload=ActionRequest(
            idempotency_key=uuid.uuid4(), version=revision.version, action="preview"
        ),
    )
    assert process_job(preview.pk)
    assert len(provider) == calls_before
    job = services.request_action(
        profile=site[1],
        revision_id=revision.pk,
        payload=ActionRequest(
            idempotency_key=uuid.uuid4(), version=revision.version, action="verify"
        ),
    )
    assert process_job(job.pk)
    assert len(provider) == calls_before + 1


def test_wire_schema_requires_each_frozen_section_once_and_adapter_restores_order(
    site, settings, monkeypatch
):
    import httpx
    from django.utils import timezone
    from edilcloud.modules.elaborati.provider import structured_response

    revision = baseline.create(site)
    job = revision.jobs.get()
    job.state = "running"
    job.lease_token = uuid.uuid4()
    job.lease_expires_at = timezone.now() + timedelta(minutes=8)
    job.save()
    settings.OPENAI_API_KEY = "test-private-key"
    keys = [s["key"] for s in revision.template_snapshot["sections"]]

    def reply(request):
        body = json.loads(request.content)
        section_schema = body["text"]["format"]["schema"]["properties"]["sections"]
        assert section_schema["type"] == "object" and section_schema["required"] == keys
        assert section_schema["additionalProperties"] is False
        assert "max_output_tokens" not in body
        value = {
            "title": "Rapporto giornaliero",
            "subtitle": "Verifiche del fronte B203",
            "photographs": [],
            "sections": {
                key: {"paragraphs": [], "lists": [], "tables": []} for key in reversed(keys)
            },
        }
        return httpx.Response(
            200,
            json={
                "id": "strict-template-result",
                "status": "completed",
                "usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(value)}],
                    }
                ],
            },
        )

    original = httpx.Client
    monkeypatch.setattr(
        "edilcloud.modules.elaborati.provider.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(reply)),
    )
    result = structured_response(
        job=job,
        stage="document_composition",
        schema=Composition,
        instructions="Use frozen sections.",
        data={"template": revision.template_snapshot},
    )
    assert [s.key for s in result.sections] == keys
    editor = editor_from_composition(result, revision.template_snapshot)
    assert editor["attrs"] == {
        "documentTitle": "Rapporto giornaliero",
        "subtitle": "Verifiche del fronte B203",
    }


def test_reference_pagination_repeats_table_headers_and_loses_no_rows(
    site, provider, settings, tmp_path
):
    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    if chrome.exists():
        settings.ELABORATI_CHROMIUM_EXECUTABLE = str(chrome)
    revision = baseline.generate(site)
    source = next(s["id"] for s in revision.evidence["sources"] if s["kind"] == "post")

    def cell(text, header=False):
        return {
            "type": "tableHeader" if header else "tableCell",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {
                        "sectionKey": "section_2",
                        "sourceIds": [] if header else [source],
                        "nature": "reported",
                    },
                    "content": [{"type": "text", "text": text}],
                }
            ],
        }

    table = {
        "type": "table",
        "content": [
            {"type": "tableRow", "content": [cell("Registro riscontri", True), cell("Stato", True)]}
        ],
    }
    for index in range(95):
        table["content"].append(
            {
                "type": "tableRow",
                "content": [
                    cell(f"RISCONTRO-{index:03d} · rilievo del fronte B203"),
                    cell("In attesa della verifica dichiarata."),
                ],
            }
        )
    revision.editor_doc["content"].insert(3, table)
    pdf_bytes = render_pdf(revision=revision, profile=site[1])
    (tmp_path / "reference-table.pdf").write_bytes(pdf_bytes)
    import pypdfium2

    with pypdfium2.PdfDocument(pdf_bytes) as pdf:
        assert len(pdf) >= 3
        text = ""
        header_pages = 0
        for i in range(len(pdf)):
            page = pdf[i]
            text_page = page.get_textpage()
            try:
                current = text_page.get_text_range()
                text += current
                header_pages += "Registro riscontri" in current
                assert "EDILCLOUD" in current and f"{i + 1} / {len(pdf)}" in current
            finally:
                text_page.close()
                page.close()
        assert header_pages >= 3
        assert all(text.count(f"RISCONTRO-{index:03d}") == 1 for index in range(95))


def test_source_register_heading_and_metadata_follow_first_row_over_page_break():
    from edilcloud.modules.elaborati.reference_layout import layout_html, paginate
    from edilcloud.modules.elaborati.pdf_labels import labels
    from playwright.sync_api import sync_playwright

    chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
    markup = layout_html(
        language="it",
        company="Impresa QA",
        logo="",
        title="Relazione QA",
        subtitle="",
        project="B203",
        address="",
        code="EL-QA",
        state="Bozza",
        period="16/10/2026",
        prepared="16/10/2026",
        author="Laura",
        words=labels("it"),
        body='<div id="filler"></div><h2 class="references-title">Registro delle fonti</h2>'
        '<p class="closing">Fonti utilizzate: 1</p><table><tbody><tr><td style="height:90px">Fonte primaria</td></tr></tbody></table>',
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, **({"executable_path": str(chrome)} if chrome.exists() else {})
        )
        try:
            page = browser.new_page()
            page.set_content(markup)
            page.evaluate(
                "() => {const p=document.querySelector('#filler');const footer=document.querySelector('footer').getBoundingClientRect().top;p.style.height=(footer-p.getBoundingClientRect().top-80)+'px'}"
            )
            result = paginate(page)
            assert result["pages"] == 2
            assert page.locator(".sheet").nth(0).locator("h2.references-title").count() == 0
            assert (
                page.locator(".sheet").nth(1).locator("h2.references-title,p.closing,table").count()
                == 3
            )
            assert page.locator("td").inner_text() == "Fonte primaria"
        finally:
            browser.close()
