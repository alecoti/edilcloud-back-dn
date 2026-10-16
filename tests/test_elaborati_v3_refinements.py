"""Acceptance regressions for policy scope, global facts and bounded writing."""

from copy import deepcopy
from datetime import timedelta
import json

import httpx
import pytest
from django.utils import timezone

from edilcloud.modules.elaborati import intelligence_writing as writing
from edilcloud.modules.elaborati.checkpoints import run_step
from edilcloud.modules.elaborati.content import Claim, Composition, ReasoningResult, Section
from edilcloud.modules.elaborati.editorial import editorial_contract
from edilcloud.modules.elaborati.errors import IncompleteDocumentOutput
from edilcloud.modules.elaborati.intelligence_contracts import (
    DocumentaryFact, DocumentPlan, FactAllocation, FactReconciliation, ReconciliationResult, SourceReference,
)
from edilcloud.modules.elaborati.intelligence_reconciliation import reconcile_global
from edilcloud.modules.elaborati.inventory import build_inventory
from edilcloud.modules.elaborati.models import DocumentAIUsage
from edilcloud.modules.elaborati.preflight import fast_review_reason
from edilcloud.modules.elaborati.provider import strict_response_schema, structured_response
from edilcloud.modules.projects.models import PostComment, ProjectPost
from tests import test_elaborati as baseline
from tests.test_elaborati_v3_inventory import inventory_job

site = baseline.site
pytestmark = pytest.mark.django_db


def fact(number, *, category="finding", nature="declared", text=None):
    text = text or f"Rilievo numero {number} in area indipendente {number}."
    return DocumentaryFact(id=f"f{number}", text=text, nature=nature, category=category,
        event_date="2026-10-16", author="Laura", critical=True, relevant=True,
        relevance_reason="Fatto pertinente", references=[SourceReference(
            source_id=f"post:{number}", part_id=f"part:{number}", page=None, quote=text)])


@pytest.mark.parametrize("document_type,keeps_history", [("daily_report", False), ("periodic_report", True), ("issue_report", True)])
def test_policy_controls_history_and_keeps_antecedents_distinct_from_period(site, document_type, keeps_history):
    project, owner, *_ = site
    old = ProjectPost.objects.create(project=project, author=owner, text="Criticità originata due mesi prima.")
    ProjectPost.objects.filter(pk=old.pk).update(published_date=timezone.now() - timedelta(days=60))
    early = PostComment.objects.create(post=old, author=owner, text="Verifica ancora richiesta.")
    PostComment.objects.filter(pk=early.pk).update(created_at=timezone.now() - timedelta(days=59))
    job = inventory_job(site, document_type)
    build_inventory(job)
    assert job.evidence_items.filter(source_id=f"post:{old.pk}").exists() is keeps_history
    assert job.evidence_items.filter(source_id=f"comment:{early.pk}").exists() is keeps_history
    job.refresh_from_db()
    assert job.workflow_state["document_policy"]["scope_rules"]
    if keeps_history:
        assert job.evidence_items.get(source_id=f"post:{old.pk}").payload["data"]["outside_period_context"]


def test_daily_keeps_old_parent_context_but_not_all_old_conversation(site):
    project, owner, *_ = site
    old = ProjectPost.objects.create(project=project, author=owner, text="Origine storica.")
    ProjectPost.objects.filter(pk=old.pk).update(published_date=timezone.now() - timedelta(days=30))
    early = PostComment.objects.create(post=old, author=owner, text="Messaggio storico.")
    PostComment.objects.filter(pk=early.pk).update(created_at=timezone.now() - timedelta(days=29))
    current = PostComment.objects.create(post=old, author=owner, text="Oggi è stata eseguita la verifica.")
    job = inventory_job(site)
    build_inventory(job)
    assert job.evidence_items.get(source_id=f"post:{old.pk}").payload["data"]["outside_period_context"]
    assert job.evidence_items.filter(source_id=f"comment:{current.pk}").exists()
    assert not job.evidence_items.filter(source_id=f"comment:{early.pk}").exists()


def test_global_pass_connects_origin_and_outcome_in_distant_groups_and_restores_checkpoint(site, monkeypatch):
    job = inventory_job(site, "issue_report")
    facts = [fact(i) for i in range(70)]
    facts[0] = fact(0, text="Crepa segnalata nella parete est del piano primo.")
    facts[-1] = fact(69, category="outcome", nature="verified", text="Verifica finale della crepa: esito regolare.")
    local = {"facts": {f.id: dict(fact_id=f.id, canonical_fact_id=f.id, relevant=True,
        reason="Distinto", conflicts_with=[], related_fact_ids=[]) for f in facts}, "conflicts": []}
    calls = []

    def compare(**kwargs):
        cards = kwargs["data"]["canonical_facts"]
        ids = {card["fact_id"] for card in cards}
        calls.append(ids)
        return ReconciliationResult(facts=[FactReconciliation(
            fact_id=key, canonical_fact_id=key, relevant=True, reason="Cronologia distinta",
            conflicts_with=[], related_fact_ids=["f69"] if key == "f0" and "f69" in ids else []) for key in ids])

    monkeypatch.setattr("edilcloud.modules.elaborati.intelligence_reconciliation.specialist", compare)
    output = reconcile_global(job, facts, local, {})
    assert any({"f0", "f69"} <= ids for ids in calls)
    assert output["facts"]["f0"]["related_fact_ids"] == ["f69"]
    assert output["facts"]["f69"]["related_fact_ids"] == ["f0"]
    assert output["facts"]["f0"]["canonical_fact_id"] != output["facts"]["f69"]["canonical_fact_id"]
    assert set(output["facts"]) == {f.id for f in facts} and output["global_complete"]
    count = len(calls)
    assert reconcile_global(job, facts, local, {}) == output
    assert len(calls) == count, "A completed global pass must not be purchased again"


def test_global_reconciliation_rejects_merging_execution_with_verification(site, monkeypatch):
    job = inventory_job(site)
    facts = [fact(0, nature="executed"), fact(1, nature="verified")]
    local = {"facts": {f.id: dict(fact_id=f.id, canonical_fact_id=f.id, relevant=True,
        reason="Distinto", conflicts_with=[], related_fact_ids=[]) for f in facts}, "conflicts": []}
    monkeypatch.setattr("edilcloud.modules.elaborati.intelligence_reconciliation.specialist", lambda **kwargs:
        ReconciliationResult(facts=[FactReconciliation(fact_id=f.id, canonical_fact_id="f0", relevant=True,
            reason="Erroneamente equivalenti", conflicts_with=[]) for f in facts]))
    output = reconcile_global(job, facts, local, {})
    assert output["facts"]["f0"]["canonical_fact_id"] == "f0"
    assert output["facts"]["f1"]["canonical_fact_id"] == "f1"
    assert output["global_complete"] and len(output["facts"]) == 2
    assert output["rejected_merges"] == [{"fact_ids": ["f0", "f1"], "reason": "different_nature_category_or_date"}]


def test_small_document_is_promoted_for_extracted_critical_conditions_or_too_many_facts():
    assert fast_review_reason([fact(0, category="activity")], {"issues": []}) == ""
    assert fast_review_reason([fact(0, category="condition")], {"issues": []})
    assert fast_review_reason([fact(i, category="activity") for i in range(7)], {"issues": []})
    assert fast_review_reason([fact(0, category="activity")], {"issues": [{"severity": "blocking"}]})


def test_policy_importance_does_not_reintroduce_explicitly_out_of_scope_conditions():
    from edilcloud.modules.elaborati.intelligence_contracts import enforce_fact_policy
    from edilcloud.modules.elaborati.policies import policy_for

    outside = fact(0, category="condition", text="Condizione contenuta in un documento successivo alla riunione.")
    outside.relevant = False
    outside.relevance_reason = "Documento successivo al coordinamento richiesto; non attesta lo stato alla riunione."
    inside = fact(1, category="condition", text="Condizione stabilita durante la riunione richiesta.")
    inside.critical = False
    parts = [{"part_id": f"part:{i}", "origin_kind": "document"} for i in range(2)]
    enforce_fact_policy([outside, inside], parts, policy_for("coordination"))
    assert outside.relevant is False and outside.critical is False
    assert outside.relevance_reason
    assert inside.relevant is True and inside.critical is True


def test_writer_contract_contains_only_its_section_and_preserves_the_correct_brief(site):
    job = inventory_job(site, "issue_report")
    # inventory_job changes storage type but not the template; use its actual
    # matching snapshot as production create does.
    from edilcloud.modules.elaborati.registry import template_for

    job.revision.template_snapshot = template_for("issue_report")
    value = editorial_contract(job.revision, section_keys={"section_4"})
    assert [s["key"] for s in value["sections"]] == ["section_4"]
    assert "Ultimo esito" in value["sections"][0]["purpose"]
    assert set(value["document_structure"]["required_tables"]) <= {"section_4"}
    job.revision.template_snapshot["sections"] = [job.revision.template_snapshot["sections"][3]]
    assert editorial_contract(job.revision, section_keys={"section_4"})["sections"] == value["sections"]


def test_planned_subsections_are_bounded_and_every_fact_is_assigned_once():
    facts = [fact(i, text="Rilievo documentato " + str(i) + " " + "x" * 500) for i in range(27)]
    template = {"sections": [{"key": "section_2", "label": "Lavorazioni"}]}
    plan = DocumentPlan(allocations=[FactAllocation(fact_id=f.id, section_key="section_2", included=True,
        reason="Pertinente", subsection_path=["Impianti elettrici", "Piano terra" if i < 16 else "Piano primo"])
        for i, f in enumerate(facts)], requirements=[])
    tasks = writing.writing_tasks(facts, plan, template)
    assert len(tasks) >= 4 and all(len(t["fact_ids"]) <= writing.WRITER_MAX_FACTS for t in tasks)
    assert sorted(f for t in tasks for f in t["fact_ids"]) == sorted(f.id for f in facts)
    assert {tuple(t["subsection_path"]) for t in tasks} == {
        ("Impianti elettrici", "Piano terra"), ("Impianti elettrici", "Piano primo")}


def test_incomplete_parent_splits_into_saved_children_without_rebuying_successful_leaves(site, monkeypatch):
    job = inventory_job(site)
    facts = [fact(i) for i in range(4)]
    known = {f.id: f for f in facts}
    calls = []

    def write(_job, **kwargs):
        ids = [f.id for f in kwargs["facts"]]

        def execute(_step):
            calls.append(ids)
            if len(ids) == 4:
                raise IncompleteDocumentOutput("Troncato")
            return Composition(title="QA", sections=[Section(key="section_1", paragraphs=[
                Claim(text=f.text, source_ids=[f.references[0].source_id], nature="reported", fact_ids=[f.id])
                for f in kwargs["facts"]])], photographs=[])

        return run_step(job=job, key=kwargs["key"], kind="document_section", data={"facts": ids},
                        execute=execute, schema=Composition)

    monkeypatch.setattr(writing, "write_partition", write)
    task = {"key": "write:root", "section": "section_1", "fact_ids": list(known),
            "subsection_path": ["Impianti"], "correction": None}
    outputs = writing.write_task(job, task=task, known=known, template={}, bundle={})
    assert len(outputs) == 2 and job.steps.get(key="write:root").state == "incomplete_output"
    assert job.steps.filter(kind="document_partition", state="completed").count() == 1
    assert len(calls) == 3
    assert len(writing.write_task(job, task=task, known=known, template={}, bundle={})) == 2
    assert len(calls) == 3
    assert [fid for _value, leaf in outputs for fid in leaf["fact_ids"]] == list(known)


def test_incomplete_response_is_billed_once_never_completed_or_silently_applied(site, settings, monkeypatch):
    job = inventory_job(site)
    settings.OPENAI_API_KEY = "synthetic-key"
    calls = []
    payload = {"id": "incomplete-v3-test", "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "usage": {"input_tokens": 10, "output_tokens": 128000, "total_tokens": 128010},
        "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"facts":['}]}]}

    def reply(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=payload)

    original = httpx.Client
    monkeypatch.setattr("edilcloud.modules.elaborati.provider.httpx.Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(reply)))
    before = deepcopy(job.revision.editor_doc)
    for _ in range(2):
        with pytest.raises(IncompleteDocumentOutput):
            run_step(job=job, key="section-overflow", kind="document_section", data={}, schema=ReasoningResult,
                     execute=lambda _step: structured_response(job=job, stage="document_section", schema=ReasoningResult,
                        instructions="Restituisci JSON", data={}))
    step = job.steps.get(key="section-overflow")
    assert step.state == step.attempts.get().state == "incomplete_output"
    assert not step.output and not step.output_hash and step.completed_at is None
    assert len(calls) == 1 and "max_output_tokens" not in calls[0]
    assert DocumentAIUsage.objects.get(job=job).total_tokens == 128010
    assert job.revision.editor_doc == before


def test_global_response_schema_requires_every_canonical_id_and_prevents_unknown_relations():
    cards = [{"fact_id": "origin"}, {"fact_id": "outcome"}]
    schema = strict_response_schema(ReconciliationResult, data={"canonical_facts": cards})
    assert schema["properties"]["facts"]["required"] == ["origin", "outcome"]
    assert schema["properties"]["facts"]["additionalProperties"] is False
    row = schema["$defs"]["FactReconciliation"]
    assert "fact_id" not in row["properties"]
    assert row["properties"]["related_fact_ids"]["items"]["enum"] == ["origin", "outcome"]


def test_provider_decodes_complete_keyed_canonical_facts_without_billing_another_validation_call(site, settings, monkeypatch):
    job = inventory_job(site)
    settings.OPENAI_API_KEY = "synthetic-key"
    calls = []

    def reply(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "canonical-keyed-test", "status": "completed",
            "max_output_tokens": None, "service_tier": "default",
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
            "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                "facts": {key: {"canonical_fact_id": key, "relevant": True, "reason": "Evoluzione distinta",
                    "conflicts_with": [], "related_fact_ids": [other]} for key, other in [("origin", "outcome"), ("outcome", "origin")]}
            })}]}]})

    original = httpx.Client
    monkeypatch.setattr("edilcloud.modules.elaborati.provider.httpx.Client",
                        lambda **kwargs: original(transport=httpx.MockTransport(reply)))
    result = structured_response(job=job, stage="document_reconcile_global", schema=ReconciliationResult,
        instructions="Restituisci JSON", data={"canonical_facts": [{"fact_id": "origin"}, {"fact_id": "outcome"}]})
    assert [f.fact_id for f in result.facts] == ["origin", "outcome"]
    assert len(calls) == 1 and "max_output_tokens" not in calls[0]
    audit = job.revision.audit.get(action="ai.response")
    assert audit.detail["output_limit"] is None and audit.detail["output_policy"] == "provider_default"


def test_writer_subsection_hierarchy_survives_canonical_assembly_and_validation():
    from edilcloud.modules.elaborati.content import editor_from_composition, validate_editor

    template = {"sections": [{"key": "section_2", "label": "Stato delle lavorazioni"}]}
    outputs, tasks = [], []
    for i, path in enumerate((["Impianti elettrici", "Piano terra"], ["Impianti elettrici", "Piano primo"])):
        outputs.append(Composition(title="QA", sections=[Section(key="section_2", paragraphs=[
            Claim(text=f"Attività {i}", source_ids=[], nature="unverified")])], photographs=[]))
        tasks.append({"key": f"unit:{i}", "section": "section_2", "subsection_path": path})
    composition = writing.assemble_partitions(outputs, tasks, template, title="QA")
    doc = validate_editor(editor_from_composition(composition, template), {"sources": []}, template)
    headings = [(node["attrs"]["level"], node["content"][0]["text"]) for node in doc["content"] if node["type"] == "heading"]
    assert headings == [(2, "Stato delle lavorazioni"), (3, "Impianti elettrici"), (4, "Piano terra"), (4, "Piano primo")]


def test_noncontiguous_metadata_quote_becomes_separate_exact_passages_without_loosening_post_checks():
    from edilcloud.modules.elaborati.intelligence_contracts import ReaderResult, SourceDisposition, validate_reader

    part = {"part_id": "meta", "source_id": "project:1", "page": None, "origin_kind": "project",
            "text": '{"address":"Via A","description":"","company":"Alfa"}'}
    item = fact(0, category="other")
    item.references = [SourceReference(source_id="project:1", part_id="meta", page=None,
                                      quote='"address":"Via A","company":"Alfa"')]
    result = ReaderResult(facts=[item], sources=[SourceDisposition(part_id="meta", status="read", reason="Anagrafica")])
    validate_reader(result, [part])
    assert [r.quote for r in result.facts[0].references] == ['"address":"Via A"', '"company":"Alfa"']
    result.facts[0].references[0].quote = '"address":"Via B"'
    with pytest.raises(ValueError, match="passaggio citato"):
        validate_reader(result, [part])
    result.facts[0].references[0].quote = '"address":"Via A","company":"Alfa"'
    with pytest.raises(ValueError, match="passaggio citato"):
        validate_reader(result, [{**part, "origin_kind": "post"}])


def test_small_section_keeps_one_writer_without_creating_microsections_for_each_fact():
    facts = [fact(i) for i in range(4)]
    plan = DocumentPlan(allocations=[FactAllocation(fact_id=f.id, section_key="section_2", included=True,
        reason="Pertinente", subsection_path=["Parete est", f"Singolo aggiornamento {i}"])
        for i, f in enumerate(facts)], requirements=[])
    tasks = writing.writing_tasks(facts, plan, {"sections": [{"key": "section_2", "label": "Cronologia"}]})
    assert len(tasks) == 1 and tasks[0]["subsection_path"] == []
    assert tasks[0]["fact_ids"] == [f.id for f in facts]
