import pytest
from django.test import Client

from edilcloud.modules.assistant.answer_planner import infer_depth, infer_presentation
from edilcloud.modules.assistant.models import ProjectAssistantGraphSnapshot, ProjectAssistantWikiPage
from edilcloud.modules.assistant.query_router import classify_assistant_query
from edilcloud.modules.assistant.services import build_tone_rules, prepare_project_assistant_run
from tests.test_projects_api import auth_headers, create_project_fixture, create_workspace_profile


@pytest.mark.parametrize("question", [
    "Non ho capito come e stato risolto il problema sul manicotto?",
    "Mi fai un riassunto di quello che e accaduto?",
    "Spiegami il motivo e cosa e successo.",
])
def test_explanations_allow_expanded_answers(question):
    assert infer_depth(question, classify_assistant_query(question)) == "expanded"
    assert infer_presentation(question, classify_assistant_query(question)) == "adaptive"


def test_explicit_brevity_still_takes_precedence():
    question = "Spiegami brevemente come e stato risolto il problema."
    assert infer_depth(question, classify_assistant_query(question)) == "compact"
    assert "Practical does not mean telegraphic" in " ".join(build_tone_rules("pragmatico"))


@pytest.mark.django_db
def test_assistant_sources_are_project_scoped_and_do_not_rebuild_memory():
    _, _, owner = create_workspace_profile(email="source.owner@example.com", password="devpass123")
    project, *_ = create_project_fixture(owner)
    other_project, *_ = create_project_fixture(owner)
    wiki = ProjectAssistantWikiPage.objects.create(project=project, slug="timeline", title="Timeline verificata", body_markdown="## Prima del getto\n\nForo spostato di 12 cm.", is_stale=False)
    ProjectAssistantWikiPage.objects.create(project=other_project, slug="timeline", title="Altro progetto", body_markdown="Contenuto escluso")
    ProjectAssistantGraphSnapshot.objects.create(project=project, summary_markdown="La verifica precede il getto.")
    document = project.documents.create(title="Verbale getto", document="sources/verbale.pdf")
    foreign_document = other_project.documents.create(title="Riservato", document="sources/altro.pdf")
    client = Client()
    headers = auth_headers(client, email=owner.email, password="devpass123")
    url = f"/api/v1/projects/{project.id}/assistant/source"

    for key, expected in [
        (f"project_wiki:{project.id}:timeline", wiki.body_markdown),
        (f"project_graph:{project.id}", "La verifica precede il getto."),
        (f"document:{document.id}", ""),
    ]:
        response = client.get(url, {"source_key": key}, **headers)
        assert response.status_code == 200
        assert response.json()["content"] == expected
        assert response.json()["source_key"] == key
    response = client.get(url, {"source_key": f"document:{document.id}"}, **headers)
    assert response.json()["mime_type"] == "application/pdf"
    assert "verbale.pdf" in response.json()["file_url"]
    for key in [f"project_wiki:{other_project.id}:timeline", f"project_graph:{other_project.id}", f"document:{foreign_document.id}", "../../secrets", f"project_wiki:{project.id}:missing"]:
        assert client.get(url, {"source_key": key}, **headers).status_code == 404
    assert Client().get(url, {"source_key": f"document:{document.id}"}).status_code == 401
    _, _, outsider = create_workspace_profile(email="source.outsider@example.com", password="devpass123")
    other_headers = auth_headers(client, email=outsider.email, password="devpass123")
    assert client.get(url, {"source_key": f"document:{document.id}"}, **other_headers).status_code == 404


@pytest.mark.django_db
def test_follow_up_explains_instead_of_repeating_old_deliverables(monkeypatch):
    _, _, owner = create_workspace_profile(email="source.explanation@example.com", password="devpass123")
    project, *_ = create_project_fixture(owner)
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)
    prepared = prepare_project_assistant_run(profile=owner, project_id=project.id, message="Non ho capito come e stato risolto il problema sul manicotto?")
    assert prepared.answer_plan.depth == "expanded"
    assert "do not simply repeat the previous sentence" in prepared.system_prompt
    assert "retain useful context, not obsolete deliverables" in prepared.system_prompt
    assert "Brevity is not a default constraint" in prepared.system_prompt
    assert "no further problems or delays" in prepared.system_prompt
    assert "CITATION_CONTRACT" in prepared.user_prompt
    assert "AVAILABLE_SOURCE_REFERENCES" in prepared.user_prompt
