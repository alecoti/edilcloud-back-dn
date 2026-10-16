import pytest
import uuid

from edilcloud.modules.elaborati import engine
from edilcloud.modules.elaborati.content import QualityResult
from edilcloud.modules.elaborati.jobs import process_job
from edilcloud.modules.elaborati.provider import DocumentProviderError
from edilcloud.modules.elaborati.schemas import ActionRequest, SaveRequest
from edilcloud.modules.elaborati import services
from tests import test_elaborati as baseline

site = baseline.site
provider = baseline.provider
pytestmark = pytest.mark.django_db


def test_identical_new_revision_retains_factual_review_but_never_pdf_or_signature(
    site, provider, monkeypatch
):
    from copy import deepcopy
    from edilcloud.modules.elaborati.publication import publish_revision

    monkeypatch.setattr(
        "edilcloud.modules.elaborati.renderer.render_pdf", lambda **kwargs: b"%PDF-frozen"
    )
    original = baseline.prepare(site, baseline.generate(site))
    original = publish_revision(
        profile=site[1],
        revision_id=original.pk,
        version=original.version,
        preview_hash=original.preview_hash,
    )
    original_quality = deepcopy(original.quality)
    revision = services.new_revision(profile=site[1], revision_id=original.pk)
    assert revision.quality == original_quality and revision.editor_doc == original.editor_doc
    assert not revision.preview_file and not revision.preview_hash and not revision.signature_audit
    calls = len(provider)
    revision = baseline.prepare(site, revision)
    assert len(provider) == calls
    edited = deepcopy(revision.editor_doc)
    edited["content"][1]["content"][0]["text"] += " Modifica da verificare."
    revision = services.save_revision(
        profile=site[1],
        revision_id=revision.pk,
        payload=SaveRequest(version=revision.version, editor_doc=edited),
    )
    assert not revision.quality["passed"] and not revision.preview_hash
    assert not revision.preview_content_hash and revision.preview_expires_at is None


def test_incomplete_ordering_hint_keeps_all_generated_cells_and_lists(site, provider):
    from edilcloud.modules.elaborati.content import BlockPlacement, editor_from_composition
    from edilcloud.modules.elaborati.models import DocumentAudit
    from tests.test_elaborati_editorial import composition

    revision = baseline.generate(site)
    source = next(s["id"] for s in revision.evidence["sources"] if s["kind"] == "post")
    value = composition(revision.template_snapshot, source)
    expected = editor_from_composition(value, revision.template_snapshot)
    value.sections[0].layout = [BlockPlacement(kind="paragraph", index=0)]
    actual = engine.compose_editor(revision.jobs.get(), value)
    assert actual == expected
    assert DocumentAudit.objects.filter(
        revision=revision, action="ai.layout_completed"
    ).get().detail == {"sections": [{"section_key": "section_1", "blocks": 2}]}
    value.sections[0].layout.append(BlockPlacement(kind="paragraph", index=0))
    value.sections[0].layout.append(BlockPlacement(kind="table", index=8))
    assert engine.compose_editor(revision.jobs.get(), value) == expected
    detail = (
        DocumentAudit.objects.filter(revision=revision, action="ai.layout_completed")
        .latest("created_at")
        .detail
    )
    assert detail["sections"] == [{"section_key": "section_1", "blocks": 0, "ignored_hints": 2}]


def test_prompt_keeps_professional_roles_separate_from_signing_permissions():
    from edilcloud.modules.elaborati.registry import template_for

    template = template_for("periodic_report")
    assert "signatory_roles" not in engine.prompt_template(template)
    assert template["signatory_roles"] == ["o", "d", "m"]
    bundle = {
        "sources": [
            {
                "id": "member:1",
                "kind": "member",
                "data": {
                    "name": "Laura",
                    "role": "o",
                    "professional_roles": ["cse"],
                    "presence": "unknown",
                },
            }
        ]
    }
    result = engine.prompt_bundle(bundle)
    assert "role" not in result["sources"][0]["data"]
    assert result["sources"][0]["data"]["professional_roles"] == ["cse"]
    assert bundle["sources"][0]["data"]["role"] == "o"


def test_failed_correction_keeps_the_first_draft_and_its_blocking_findings(
    site, provider, monkeypatch
):
    original = engine.structured_response

    def reply(**kwargs):
        if kwargs["stage"] == "document_quality":
            return QualityResult(
                issues=[
                    {
                        "section_key": "section_1",
                        "text": "Verifica",
                        "severity": "blocking",
                        "explanation": "Esito da correggere prima della pubblicazione.",
                    }
                ],
                missing_data=[],
            )
        if kwargs["stage"] == "document_correction":
            raise DocumentProviderError("Formato della correzione non valido.")
        return original(**kwargs)

    monkeypatch.setattr(engine, "structured_response", reply)
    revision = baseline.create(site)
    assert process_job(revision.jobs.get().pk)
    revision.refresh_from_db()
    assert revision.jobs.get().state == "completed" and revision.jobs.get().stage == "review"
    assert revision.editor_doc and not revision.quality["passed"]
    assert revision.quality["correction_failed"] and revision.quality["correction_passes"] == 1
    assert any(i["severity"] == "blocking" for i in revision.quality["issues"])


def test_quality_review_receives_real_tables_and_headers_instead_of_flattened_sentences(
    site, provider, monkeypatch
):
    from edilcloud.modules.elaborati.content import editor_from_composition
    from tests.test_elaborati_editorial import composition

    revision = baseline.generate(site)
    source = next(s["id"] for s in revision.evidence["sources"] if s["kind"] == "post")
    editor = editor_from_composition(
        composition(revision.template_snapshot, source), revision.template_snapshot
    )
    revision = services.save_revision(
        profile=site[1],
        revision_id=revision.pk,
        payload=SaveRequest(version=revision.version, editor_doc=editor),
    )
    original = engine.structured_response
    captured = []

    def reply(**kwargs):
        if kwargs["stage"] == "document_quality":
            captured.append(kwargs["data"])
        return original(**kwargs)

    monkeypatch.setattr(engine, "structured_response", reply)
    job = services.request_action(
        profile=site[1],
        revision_id=revision.pk,
        payload=ActionRequest(
            idempotency_key=uuid.uuid4(), version=revision.version, action="verify"
        ),
    )
    assert process_job(job.pk)
    assert captured[0]["document"] == editor and "claims" not in captured[0]
    assert captured[0]["structure_validation"]["passed"] is True
    table = next(n for n in captured[0]["document"]["content"] if n["type"] == "table")
    assert table["content"][0]["content"][0]["type"] == "tableHeader"


def test_invalid_table_nesting_is_rejected_before_a_paid_ai_review(site, provider):
    from copy import deepcopy

    revision = baseline.generate(site)
    doc = deepcopy(revision.editor_doc)
    paragraph = deepcopy(doc["content"][1])
    doc["content"].append(
        {"type": "table", "content": [{"type": "tableRow", "content": [paragraph]}]}
    )
    calls = len(provider)
    with pytest.raises(ValueError, match="Struttura"):
        engine.verify_document(revision.jobs.get(), editor=doc)
    assert len(provider) == calls
