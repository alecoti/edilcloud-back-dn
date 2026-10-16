from copy import deepcopy

import pytest

from edilcloud.modules.elaborati.content import Composition, editor_from_composition, editor_claims
from edilcloud.modules.elaborati.document_structure import registers_for, decode_registers
from edilcloud.modules.elaborati.fields import fields_in
from edilcloud.modules.elaborati.provider import strict_response_schema, decode_document_parts
from edilcloud.modules.elaborati.registry import TYPES, template_for
from tests.test_elaborati_editorial import composition


@pytest.mark.parametrize("document_type", TYPES)
@pytest.mark.parametrize("language", ["it", "en", "fr", "ro", "ru", "ar"])
def test_required_registers_have_real_editable_cells_in_every_type_and_language(
    document_type, language
):
    template = template_for(document_type, language)
    before = deepcopy(template)
    schema = strict_response_schema(Composition, template)
    value = composition(template, "post:1").model_dump()
    expected_columns = []
    field_ids = []
    for section in value["sections"]:
        section["tables"] = []
        definitions = registers_for(template).get(section["key"], [])
        if not definitions:
            continue
        section["required_tables"] = {}
        wire = schema["properties"]["sections"]["properties"][section["key"]]
        assert "required_tables" in wire["required"]
        assert wire["properties"]["required_tables"]["required"] == [d["key"] for d in definitions]
        for definition in definitions:
            row = {}
            for column in definition["columns"]:
                key = f"{section['key']}.{definition['key']}.{column}"
                field_ids.append(key)
                row[column] = {
                    "paragraphs": [
                        {
                            "source_ids": [],
                            "nature": "unverified",
                            "parts": [
                                {
                                    "field": {
                                        "key": key,
                                        "label": definition["labels"][
                                            definition["columns"].index(column)
                                        ],
                                        "kind": "text",
                                        "unit": "",
                                    }
                                }
                            ],
                        }
                    ]
                }
            section["required_tables"][definition["key"]] = {"rows": [row]}
            expected_columns.append(definition["labels"])
    decode_document_parts(value)
    decode_registers(value, template)
    result = Composition.model_validate(value)
    doc = editor_from_composition(result, template)
    tables = [n for n in doc["content"] if n["type"] == "table"]
    actual_columns = [
        [c["content"][0]["content"][0]["text"] for c in n["content"][0]["content"]] for n in tables
    ]
    assert actual_columns == expected_columns
    assert {field["fieldId"] for field in fields_in(doc)} == set(field_ids)
    assert all(len(n["content"][0]["content"]) == len(n["content"][1]["content"]) for n in tables)
    assert not any(c["text"] in sum(expected_columns, []) for c in editor_claims(doc))
    assert template == before


def test_named_register_cannot_silently_drop_a_missing_cell():
    template = template_for("inspection")
    value = {
        "sections": [
            {"key": "section_3", "required_tables": {"checks": {"rows": [{"criterion": {}}]}}}
        ]
    }
    with pytest.raises(ValueError, match="Celle"):
        decode_registers(value, template)


def test_register_headers_distinguish_last_recorded_status_from_period_end():
    registers = registers_for(template_for("periodic_report"))
    assert registers["section_3"][0]["labels"][1] == "Ultimo stato registrato"
    assert "assenza di aggiornamenti" in registers["section_3"][0]["purpose"]


def test_full_output_allowance_is_not_cut_by_document_length_or_register_row_caps():
    from edilcloud.modules.elaborati.content import (
        Claim,
        ClaimTable,
        ReasoningResult,
        QualityResult,
    )

    template = template_for("daily_report")
    schema = strict_response_schema(Composition, template)
    for name in ("Section", "ClaimCell", "ClaimList"):
        for field in schema["$defs"][name]["properties"].values():
            if field.get("type") == "array":
                assert "maxItems" not in field
    assert "maxItems" not in schema["properties"]["photographs"]
    assert "maxItems" not in schema["$defs"]["Claim"]["properties"]["parts"]
    for section in schema["properties"]["sections"]["properties"].values():
        for register in (
            section.get("properties", {}).get("required_tables", {}).get("properties", {}).values()
        ):
            assert "maxItems" not in register["properties"]["rows"]
    for model in (ReasoningResult, QualityResult):
        assert all(
            "maxItems" not in field for field in model.model_json_schema()["properties"].values()
        )
    # The old schema rejected a register after row 24 and paragraphs after 4k
    # characters, even when the model and complete editor payload had room.
    claim = Claim(text="Riscontro documentato. " * 220, source_ids=["post:1"], nature="reported")
    table = ClaimTable(
        columns=["Riferimento", "Riscontro"], rows=[[claim, claim] for _ in range(95)]
    )
    value = composition(template, "post:1")
    value.sections[0].tables = [table]
    doc = editor_from_composition(value, template)
    register = next(node for node in doc["content"] if node["type"] == "table")
    assert len(register["content"]) == 96
    assert register["content"][-1]["content"][1]["content"][0]["content"][0]["text"] == claim.text


def test_rich_table_cell_keeps_plan_and_explicit_decision_as_distinct_claims():
    from edilcloud.modules.elaborati.content import ClaimCell, Claim, composition_claims

    template = template_for("periodic_report")
    value = composition(template, "post:1")
    value.sections[0].tables[0].rows[0][1] = ClaimCell(
        paragraphs=[
            Claim(
                text="Il piano prevede la consegna delle valvole.",
                source_ids=["document:1"],
                nature="reported",
            ),
            Claim(
                text="Laura dispone di mantenere aperta la segnalazione.",
                source_ids=["comment:2"],
                nature="decided",
            ),
        ]
    )
    doc = editor_from_composition(value, template)
    table = next(n for n in doc["content"] if n["type"] == "table")
    paragraphs = table["content"][1]["content"][1]["content"]
    assert [p["attrs"]["nature"] for p in paragraphs] == ["reported", "decided"]
    assert [p["attrs"]["sourceIds"] for p in paragraphs] == [["document:1"], ["comment:2"]]
    claims = list(composition_claims(value))
    assert any(c.nature == "reported" and c.source_ids == ["document:1"] for c in claims)
    assert any(c.nature == "decided" and c.source_ids == ["comment:2"] for c in claims)


def test_identical_generated_register_is_not_repeated_for_different_empty_field_ids():
    from edilcloud.modules.elaborati.content import Claim, ClaimCell, ClaimTable, BlockPlacement
    from edilcloud.modules.elaborati.fields import EditableField
    from edilcloud.modules.elaborati.document_structure import deduplicate_initial_tables

    template = template_for("photo_report")
    value = composition(template, "post:1")
    date = Claim(
        text="Data: {{capture_date}}",
        source_ids=[],
        nature="unverified",
        fields=[EditableField(key="capture_date", label="Data dello scatto", kind="date")],
    )
    table = ClaimTable(
        columns=["Fotografia", "Contesto", "Data"],
        rows=[
            [
                Claim(text="Foto del rilievo", source_ids=["photo:1"], nature="reported"),
                Claim(text="Locale B203", source_ids=["post:1"], nature="reported"),
                ClaimCell(paragraphs=[date]),
            ]
        ],
    )
    duplicate = deepcopy(table)
    duplicate.rows[0][2].paragraphs[0].text = "Data: {{capture_date_2}}"
    duplicate.rows[0][2].paragraphs[0].fields[0].key = "capture_date_2"
    duplicate.widths = [20, 50, 30]
    value.sections[1].tables = [table, duplicate]
    value.sections[1].layout = [BlockPlacement(kind="table", index=1)]
    assert deduplicate_initial_tables(value, template) == [
        {"section_key": "section_2", "tables": 1}
    ]
    assert len(value.sections[1].tables) == 1 and value.sections[1].layout[0].index == 0
    # A different citation or a different fact is not a duplicate.
    for change in ("source", "fact"):
        other = deepcopy(table)
        if change == "source":
            other.rows[0][0].source_ids = ["photo:2"]
        else:
            other.rows[0][1].text = "Locale B204"
        value.sections[1].tables = [table, other]
        assert not deduplicate_initial_tables(value, template)
        assert len(value.sections[1].tables) == 2
