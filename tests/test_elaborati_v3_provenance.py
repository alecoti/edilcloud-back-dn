from copy import deepcopy

import pytest

from edilcloud.modules.elaborati.content import (
    BlockPlacement, Claim, ClaimTable, Composition, Photograph, Section,
    editor_claims, editor_equivalent, editor_from_composition, validate_editor,
)
from edilcloud.modules.elaborati.fields import EditableField, fields_in
from edilcloud.modules.elaborati.intelligence_writing import assemble_partitions


def test_assembly_preserves_interleaving_headings_photos_fact_links_and_independent_fields():
    template = {"sections": [{"key": "section_1", "label": "Cronologia", "required": True}]}
    outputs = []
    for number in (1, 2):
        fact = Claim(text=f"Esito documentato {number}", source_ids=["post:1"], nature="reported", fact_ids=[f"f{number}"])
        field = Claim(text="{{hours}}", source_ids=[], nature="unverified",
                      fields=[EditableField(key="hours", label="Ore", kind="hours")])
        outputs.append(Composition(title="QA", subtitle="Sintesi", sections=[Section(
            key="section_1", paragraphs=[fact], tables=[ClaimTable(columns=["Esito", "Ore"], rows=[[fact, field]])],
            layout=[BlockPlacement(kind="heading", label=f"Fase {number}"),
                    BlockPlacement(kind="paragraph"), BlockPlacement(kind="photo"), BlockPlacement(kind="table")],
        )], photographs=[Photograph(source_id="photo:1", caption=fact, section_key="section_1")]))
    merged = assemble_partitions(outputs, [{"key": "write:1", "section": "section_1"},
                                           {"key": "write:2", "section": "section_1"}], template, title="QA")
    editor = editor_from_composition(merged, template)
    evidence = {"fact_ids": ["f1", "f2"], "sources": [{"id": "post:1", "kind": "post"}, {"id": "photo:1", "kind": "photo"}]}
    validate_editor(editor, evidence, template)
    assert len(merged.photographs) == 1
    assert merged.photographs[0].caption.fact_ids == ["f1", "f2"]
    assert [n["type"] for n in editor["content"]] == ["heading", "heading", "paragraph", "evidencePhoto", "table",
                                                      "heading", "paragraph", "table"]
    assert len({f["fieldId"] for f in fields_in(editor)}) == 2
    assert {fid for c in editor_claims(editor) for fid in c.get("fact_ids", [])} == {"f1", "f2"}
    assert outputs[1].sections[0].tables[0].rows[0][1].fields[0].key == "hours", "Inputs must stay immutable"


def test_editor_preserves_known_provenance_and_rejects_unknown_fact_ids():
    template = {"sections": [{"key": "section_1", "label": "Riscontro"}]}
    composition = Composition(title="QA", sections=[Section(key="section_1", paragraphs=[
        Claim(text="Riscontro", source_ids=["post:1"], nature="reported", fact_ids=["known"]),
    ])], photographs=[])
    editor = editor_from_composition(composition, template)
    evidence = {"fact_ids": ["known"], "sources": [{"id": "post:1", "kind": "post"}]}
    assert editor_claims(validate_editor(editor, evidence, template))[0]["fact_ids"] == ["known"]
    invalid = deepcopy(editor)
    invalid["content"][1]["attrs"]["factIds"] = ["invented"]
    with pytest.raises(ValueError, match="fatto documentale"):
        validate_editor(invalid, evidence, template)
    legacy = deepcopy(editor)
    legacy["content"][1]["attrs"].pop("factIds")
    harmless = deepcopy(legacy)
    harmless["content"][1]["attrs"]["factIds"] = []
    assert editor_equivalent(legacy, harmless)
    assert not editor_equivalent(editor, harmless)


def test_large_canonical_document_is_not_rejected_by_the_old_two_megabyte_twenty_thousand_node_caps():
    template = {"sections": [{"key": "section_1", "label": "Registrazioni"}]}
    paragraph = {"type": "paragraph", "attrs": {"sectionKey": "section_1", "sourceIds": [], "nature": "unverified"},
                 "content": [{"type": "text", "text": "Registrazione lunga da completare. " * 10}]}
    editor = {"type": "doc", "content": [deepcopy(paragraph) for _ in range(12000)]}
    assert validate_editor(editor, {"sources": []}, template) is editor
    assert len(editor["content"]) == 12000


def test_incomplete_plan_is_completed_without_losing_a_critical_fact_or_inventing_satisfied_requirements():
    from edilcloud.modules.elaborati.intelligence_contracts import (
        DocumentaryFact, SourceReference, DocumentPlan, FactAllocation,
    )
    from edilcloud.modules.elaborati.intelligence_planning import complete_plan, requirements
    from edilcloud.modules.elaborati.policies import policy_for
    from edilcloud.modules.elaborati.registry import template_for

    fact = DocumentaryFact(id="critical", text="La sospensione resta valida fino alla verifica.", nature="open",
        category="condition", event_date="2026-10-16", author="Laura", critical=True, relevant=True,
        relevance_reason="Condizione per la ripresa", references=[SourceReference(
            source_id="post:1", part_id="p1", page=None, quote="La sospensione resta valida fino alla verifica.")])
    template = template_for("issue_report")
    policy = policy_for("issue_report")
    # A typo/omission must never silently remove a critical fact or trigger a
    # fresh provider call merely to assign a deterministic section destination.
    plan = DocumentPlan(allocations=[FactAllocation(fact_id="typo", section_key="bad", included=True, reason="wrong")],
                        requirements=[])
    repaired = complete_plan(plan, [fact], policy, template)
    assert [(a.fact_id, a.included, a.section_key) for a in repaired.allocations] == [("critical", True, "section_4")]
    assert {r.requirement_id for r in repaired.requirements} == {r["id"] for r in requirements(policy, template)}
    assert all(r.status == "requires_confirmation" and r.fact_ids == [] for r in repaired.requirements)


def test_targeted_replacement_keeps_other_sections_and_filled_fields_unchanged():
    from edilcloud.modules.elaborati.intelligence_writing import replace_sections

    template = {"sections": [{"key": f"section_{i}", "label": f"Sezione {i}"} for i in (1, 2)]}
    original = editor_from_composition(Composition(title="QA", sections=[
        Section(key="section_1", paragraphs=[Claim(text="{{person}}", fields=[
            EditableField(key="person", label="Persona", kind="person")], source_ids=[], nature="unverified")]),
        Section(key="section_2", paragraphs=[Claim(text="Esito da correggere", source_ids=[], nature="unverified")]),
    ], photographs=[]), template)
    person = next(fields_in(original))
    person["value"] = "Laura Verdi"
    untouched = deepcopy(original["content"][:2])
    replacement = editor_from_composition(Composition(title="Partial", sections=[Section(key="section_2", paragraphs=[
        Claim(text="Esito corretto {{person}}", fields=[EditableField(key="person", label="Referente", kind="person")],
              source_ids=[], nature="unverified"),
    ])], photographs=[]), {"sections": [template["sections"][1]]})
    result = replace_sections(original, replacement, template, {"section_2"})
    assert result["attrs"] == original["attrs"]
    assert result["content"][:2] == untouched
    assert list(fields_in(result))[0]["value"] == "Laura Verdi"
    assert len({f["fieldId"] for f in fields_in(result)}) == 2
    assert original["content"][:2] == untouched


def test_factual_table_claim_keeps_its_column_and_surrounding_row_context():
    from edilcloud.modules.elaborati.intelligence_writing import claim_blocks

    claim = Claim(text="Parete est – tinteggiatura", source_ids=["post:1"], nature="reported", fact_ids=["f1"])
    action = Claim(text="Sospesa fino alla verifica", source_ids=["post:1"], nature="decided", fact_ids=["f1"])
    template = {"sections": [{"key": "section_1", "label": "Azioni"}]}
    editor = editor_from_composition(Composition(title="QA", sections=[Section(key="section_1", paragraphs=[], tables=[
        ClaimTable(columns=["Oggetto", "Disposizione"], rows=[[claim, action]])])], photographs=[]), template)
    blocks = claim_blocks(editor)
    assert len(blocks) == 2
    assert blocks[0]["table_column"] == "Oggetto"
    assert blocks[0]["table_row"] == ["Parete est – tinteggiatura", "Sospesa fino alla verifica"]
    assert "table_column" not in editor_claims(editor)[0], "Existing API projections remain compatible"
