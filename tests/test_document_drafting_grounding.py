import copy

import pytest

from edilcloud.modules.assistant.document_drafting import (
    build_default_document_print_payload,
    reconcile_document_print_payload,
    render_rapportino_print_payload_markdown,
    render_sopralluogo_print_payload_markdown,
)


CONTEXT = {
    "selected_task": {
        "assigned_company": {
            "id": 7,
            "name": "Aurora Costruzioni Generali",
            "tax_code": "10866270158",
            "email": "commesse@auroracostruzioni.it",
        }
    },
    "overview": {"team": []},
}


@pytest.mark.parametrize("document_type", ["giornale", "rapportino", "sopralluogo"])
def test_unknown_company_does_not_inherit_another_company_identifiers(document_type):
    date_key = "site" if document_type == "rapportino" else "project"
    draft = {
        "company": {"name": "Test Alfa", "vat": "10866270158",
                    "email": "commesse@auroracostruzioni.it", "address": "Via inventata"},
        date_key: {"date": "2026-09-28"},
        "document_reference": "GL-HALLUCINATED",
        "missing_data": [],
    }
    result = reconcile_document_print_payload(document_type, draft, {"context": {}}, CONTEXT)
    assert result["company"] == {"name": "Test Alfa", "vat": "", "email": "", "address": ""}
    assert result[date_key]["date"] == ""
    assert result["document_reference"] == ""
    assert any("Identificativi fiscali" in item for item in result["missing_data"])
    assert any("Data effettiva" in item for item in result["missing_data"])


@pytest.mark.parametrize("document_type", ["giornale", "rapportino", "sopralluogo"])
def test_known_company_gets_only_canonical_identifiers_and_selected_date(document_type):
    date_key = "site" if document_type == "rapportino" else "project"
    draft = {"company": {"name": "Aurora Costruzioni Generali", "vat": "wrong",
                         "email": "wrong@example.test", "address": "Unverified"},
             date_key: {"date": "wrong"}, "missing_data": []}
    payload = {"context": {"date_from": "2026-09-27", "date_to": "2026-09-27"}}
    result = reconcile_document_print_payload(document_type, draft, payload, CONTEXT)
    assert result["company"]["vat"] == "10866270158"
    assert result["company"]["email"] == "commesse@auroracostruzioni.it"
    assert result["company"]["address"] == ""
    assert result[date_key]["date"] == "2026-09-27"


def test_giornale_hours_are_not_person_count():
    draft = {"company": {"name": ""}, "project": {}, "missing_data": [],
             "personnel": [{"label": "Ada Test", "quantity": "2,5 ore ordinarie", "notes": "Operaia"}]}
    result = reconcile_document_print_payload(
        "giornale", draft, {"context": {}, "operator_input": {"notes": "Ada Test presente per 2,5 ore."}}, CONTEXT
    )
    assert result["personnel"][0]["quantity"] == ""
    assert "2,5 ore ordinarie" in result["personnel"][0]["notes"]


def test_rapportino_materials_heading_and_footer_do_not_claim_usage_or_legal_validity():
    draft = {"company": {"name": ""}, "site": {}, "missing_data": [],
             "materials": [{"description": "Pannelli", "unit": "pz", "quantity": "6",
                            "notes": "Consegnati, non posati"}],
             "footer_note": "Valido ai fini della contabilizzazione"}
    result = reconcile_document_print_payload(
        "rapportino", draft,
        {"context": {}, "operator_input": {"notes": "Consegnati 6 pannelli, non posati."}}, CONTEXT,
    )
    markdown = render_rapportino_print_payload_markdown(result)
    assert "## Materiali e forniture" in markdown
    assert "Consegnati, non posati" in markdown
    assert "Valido ai fini della contabilizzazione" not in markdown


def test_sopralluogo_neutral_internal_state_is_not_printed():
    draft = {"document_title": "Verbale", "company": {}, "project": {}, "inspection": {},
             "findings": [{"status": "neutral", "title": "Pannello disallineato",
                           "description": "Osservato al varco nord"}]}
    markdown = render_sopralluogo_print_payload_markdown(copy.deepcopy(draft))
    assert "Pannello disallineato" in markdown
    assert "Stato: neutral" not in markdown


@pytest.mark.parametrize("document_type", ["giornale", "rapportino", "sopralluogo"])
def test_task_assignment_and_plan_are_never_default_event_facts(document_type):
    context = copy.deepcopy(CONTEXT)
    context["selected_task"].update({"name": "Posa recinzione", "description": "Posare 12 pannelli",
                                     "date_start": "2025-08-09", "date_end": "2025-08-23"})
    context["overview"]["team"] = [{"name": "Luca Test", "role": "Capocantiere"}]
    payload = {"context": {}, "operator_input": {"notes": "Non conosco presenti o lavorazioni eseguite."},
               "evidence": {"excerpts": ["Prevista posa dei pannelli."]}}
    result = build_default_document_print_payload(
        document_type=document_type, project_id=20, payload=payload,
        prompt_context=context, generated_at="2026-09-28T00:00:00Z",
    )
    if document_type == "giornale":
        assert result["personnel"] == []
        assert result["activities"] == []
    elif document_type == "rapportino":
        assert result["workforce"] == []
        assert "Posare 12 pannelli" not in result["work_description"]
    else:
        assert result["attendees"] == []
        assert result["findings"] == []


def test_sparse_generated_giornale_cannot_promote_plan_or_team_to_facts():
    draft = {"company": {}, "project": {}, "missing_data": [],
             "summary": "Posati 12 pannelli di recinzione.",
             "personnel": [{"label": "Luca Test", "quantity": "1", "company": "Impresa", "notes": ""}],
             "activities": [
                 {"title": "Posa pannelli", "description": "Posati 12 pannelli di recinzione.",
                  "time_start": "2025-08-09", "time_end": "2025-08-23"},
                 {"title": "Evidenza dal thread 1", "description": "Prevista posa", "time_start": "", "time_end": ""},
             ]}
    payload = {"context": {}, "operator_input": {"notes": "Non conosco presenti o lavorazioni eseguite."}}
    result = reconcile_document_print_payload("giornale", draft, payload, CONTEXT)
    assert result["personnel"] == []
    assert result["activities"] == []
    assert result["summary"] == ""


def test_explicit_operator_event_preserves_real_people_activities_and_findings():
    notes = "Ada Test e Carla Test presenti al sopralluogo: osservato pannello disallineato. Ada Test ha posato 12 pannelli dalle 08:00 alle 10:30."
    payload = {"context": {}, "operator_input": {"notes": notes}}
    giornale = {"company": {}, "project": {}, "missing_data": [],
                "personnel": [{"label": "Ada Test", "quantity": "1", "notes": ""},
                              {"label": "Luca Test", "quantity": "1", "notes": ""}],
                "activities": [{"title": "Posa pannelli", "description": "Posati 12 pannelli.",
                                "time_start": "08:00", "time_end": "10:30"}]}
    result = reconcile_document_print_payload("giornale", giornale, payload, CONTEXT)
    assert [person["label"] for person in result["personnel"]] == ["Ada Test"]
    assert result["activities"][0]["time_start"] == "08:00"
    sopralluogo = {"company": {}, "project": {}, "missing_data": [],
                   "attendees": [{"name": "Carla Test"}, {"name": "Luca Test"}],
                   "findings": [{"title": "Pannello disallineato", "description": "Osservato un pannello disallineato."}]}
    result = reconcile_document_print_payload("sopralluogo", sopralluogo, payload, CONTEXT)
    assert [person["name"] for person in result["attendees"]] == ["Carla Test"]
    assert len(result["findings"]) == 1


def test_rapportino_drops_placeholder_equipment_but_preserves_declared_machine():
    payload = {"context": {}, "operator_input": {"notes": "Miniescavatore utilizzato per un'ora."}}
    draft = {"company": {}, "site": {}, "missing_data": [],
             "equipment": [{"description": "Non disponibile"},
                           {"description": "Miniescavatore", "quantity_hours": "1 ora"}]}
    result = reconcile_document_print_payload("rapportino", draft, payload, CONTEXT)
    assert result["equipment"] == [{"description": "Miniescavatore", "quantity_hours": "1 ora"}]
