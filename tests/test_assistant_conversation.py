import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from django.test import Client

from edilcloud.modules.assistant.conversation import (
    contextual_retrieval_query, conversation_input, is_contextual_follow_up, select_conversation_memory,
)
from edilcloud.modules.assistant.models import ProjectAssistantMessage, ProjectAssistantThread
from edilcloud.modules.assistant.services import (
    build_openai_responses_payload, get_project_assistant_thread, prepare_project_assistant_run, select_answer_citations,
)
from tests.test_projects_api import create_project_fixture, create_workspace_profile, auth_headers


def message(index, role, content, citations=None):
    return SimpleNamespace(id=index, role=role, content=content, citations=citations or [], created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index))


@pytest.mark.parametrize("question", ["E chi se ne occupa?", "Metti quello in tabella", "Quali sono le loro responsabilita?", "Approfondisci il secondo punto", "Per il secondo punto, scrivi una bozza", "Explain the second row"])
def test_follow_up_uses_context(question):
    assert is_contextual_follow_up(question)


@pytest.mark.parametrize("question", ["Quanti documenti?", "Fammi il punto sull'impianto elettrico", "Quali aziende partecipano al progetto?", "Fammi una tabella delle aziende del progetto"])
def test_new_topic_does_not_inherit_context(question):
    assert not is_contextual_follow_up(question)


def test_memory_retrieves_older_turns_and_preserves_markdown_within_budget():
    older = message(5, "user", "La mia priorita e il lucernario Delta, confronto con il capitolato.")
    opening = message(1, "user", "Preferisco gli aggiornamenti in inglese.")
    recent = [message(i, "user" if i % 2 else "assistant", f"Messaggio {i}\n\n| Voce | Valore |\n| --- | --- |\n| A | B |") for i in range(20, 44)]
    selected = select_conversation_memory(question="Torniamo al lucernario Delta", recent=recent, archived=[older], anchors=[opening], max_chars=5000, archive_chars=1000)
    assert older in selected and opening in selected
    assert selected[-1].id == 43
    assert "\n| Voce |" in conversation_input(selected)[-1]["content"]
    assert sum(len(item["content"]) for item in conversation_input(selected)) <= 5000


def test_prior_citations_are_rebound_not_confused_with_current_sources():
    previous = message(2, "assistant", "Ancoraggio nord [1]; altro [2].", [{"index": 1, "source_key": "post:12"}, {"index": 2, "source_key": "post:13"}])
    assert conversation_input([previous], [{"source_key": "post:12", "index": 4}])[0]["content"] == "Ancoraggio nord [4]; altro ."


def test_generated_answers_do_not_borrow_unrelated_retrieved_sources():
    selected, contract = select_answer_citations(answer="Bozza generale senza affermazioni documentate.", citations=[{"index": 1, "source_key": "post:1"}], strategy="deterministic_db", generated=True)
    assert selected == []
    assert contract == "model_without_claim_sources"


def test_provider_receives_roles_and_no_provider_side_storage():
    payload = build_openai_responses_payload(system_prompt="Policy", user_prompt="Domanda attuale", conversation_messages=[message(1, "user", "Il mio vincolo e il venerdi."), message(2, "assistant", "Ricevuto.")])
    assert [item["role"] for item in payload["input"]] == ["system", "user", "assistant", "user"]
    assert payload["input"][1]["content"] == "Il mio vincolo e il venerdi."
    assert payload["store"] is False


def test_contextual_query_retains_subject_and_does_not_mix_new_topics():
    history = [message(1, "user", "Chi segue le valvole della centrale?"), message(2, "assistant", "Idrotermica: verificare la consegna.", [{"label": "Valvole di bilanciamento centrale termica"}])]
    assert "valvole" in contextual_retrieval_query("E quando arrivano?", history)
    assert contextual_retrieval_query("Quanti documenti?", history) == "Quanti documenti?"


@pytest.mark.django_db
def test_invalid_or_foreign_thread_is_never_silently_replaced():
    _, _, owner = create_workspace_profile(email="memory.owner@example.com", password="devpass123", workspace_name="Memory QA")
    project, *_ = create_project_fixture(owner)
    other = ProjectAssistantThread.objects.create(project=project, author=None, title="Chat privata diversa")
    for thread_id in (other.id, 999999):
        with pytest.raises(ValueError, match="Conversazione non disponibile"):
            get_project_assistant_thread(project=project, profile=owner, thread_id=thread_id)


@pytest.mark.django_db
def test_preparation_keeps_history_after_reload_and_resets_scope_for_new_topic(monkeypatch):
    _, _, owner = create_workspace_profile(email="memory.reload@example.com", password="devpass123", workspace_name="Memory Reload QA")
    project, task, activity, _ = create_project_fixture(owner)
    thread = ProjectAssistantThread.objects.create(project=project, author=owner, title="Memoria", metadata={"last_context": {"task_id": task.id, "activity_id": activity.id}})
    for index in range(32):
        ProjectAssistantMessage.objects.create(project=project, thread=thread, author=owner if index % 2 == 0 else None, role="user" if index % 2 == 0 else "assistant", content="La parola di riferimento e lucernario Delta." if index == 0 else f"Aggiornamento {index}")
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)
    prepared = prepare_project_assistant_run(profile=owner, project_id=project.id, thread_id=thread.id, message="Ricordi il lucernario Delta?")
    assert any("lucernario Delta" in item.content for item in prepared.recent_messages)
    assert prepared.retrieval_context.context_scope == "project"
    assert prepared.retrieval_bundle.metrics["conversation_archived_message_count"] > 0
    assert "tables with a header separator" in prepared.system_prompt
    other = ProjectAssistantThread.objects.create(project=project, author=owner, title="Chat vuota")
    fresh = prepare_project_assistant_run(profile=owner, project_id=project.id, thread_id=other.id, message="Quanti documenti?")
    assert fresh.recent_messages == []


@pytest.mark.django_db
def test_deterministic_retrieval_can_have_a_freeform_table_answer(monkeypatch, settings):
    _, _, owner = create_workspace_profile(email="memory.table@example.com", password="devpass123", workspace_name="Memory Table QA")
    project, *_ = create_project_fixture(owner)
    settings.OPENAI_API_KEY = "test-only-not-a-real-key"
    settings.AI_ASSISTANT_CONVERSATIONAL_ENABLED = True
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return "| Partecipanti | Stato |\n| --- | --- |\n| 1 | Registrati [1] |"

    monkeypatch.setattr("edilcloud.modules.assistant.services.generate_assistant_completion", generate)
    client = Client()
    headers = auth_headers(client, email=owner.user.email, password="devpass123")
    response = client.post(f"/api/v1/projects/{project.id}/assistant", data=json.dumps({"message": "Quanti partecipanti ci sono?"}), content_type="application/json", **headers)
    assert response.status_code == 201
    assert "| Partecipanti |" in response.json()["assistant_message"]["content"]
    assert calls and "conversation_messages" in calls[0]


@pytest.mark.django_db
@pytest.mark.parametrize("stream", [False, True])
def test_conversational_summary_generates_with_history_and_keeps_citation_gate(monkeypatch, settings, stream):
    _, _, owner = create_workspace_profile(email=f"memory.summary.{stream}@example.com", password="devpass123", workspace_name="Memory Summary QA")
    project, *_ = create_project_fixture(owner)
    settings.OPENAI_API_KEY = "test-only-not-a-real-key"
    settings.AI_ASSISTANT_CONVERSATIONAL_ENABLED = True
    settings.AI_ASSISTANT_SUMMARY_GENERATION_ENABLED = False
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return "| Stato | Evidenza |\n| --- | --- |\n| Situazione registrata | Snapshot del progetto [1] |"

    monkeypatch.setattr("edilcloud.modules.assistant.services.generate_assistant_completion", generate)
    client = Client()
    headers = auth_headers(client, email=owner.user.email, password="devpass123")
    response = client.post(f"/api/v1/projects/{project.id}/assistant{'/stream' if stream else ''}", data=json.dumps({"message": "Riassunto del cantiere"}), content_type="application/json", **headers)
    if stream:
        events = b"".join(response.streaming_content).decode()
        payload = json.loads(events.split("event: done\ndata: ", 1)[1].split("\n\n", 1)[0])
    else:
        payload = response.json()
    assert "| Stato |" in payload["assistant_message"]["content"]
    assert calls
    prepared = prepare_project_assistant_run(profile=owner, project_id=project.id, thread_id=payload["thread"]["id"], message="Metti il secondo punto in tabella")
    assert prepared.route.follow_up
    assert len(prepared.recent_messages) == 2
    assert "Write an operational site update" not in prepared.system_prompt


def test_long_recent_answers_leave_room_for_opening_constraints():
    opening = message(1, "user", "Il budget proposto e 2500 euro, non superarlo.")
    recent = [message(index, "assistant", "x" * 2000) for index in range(5, 25)]
    selected = select_conversation_memory(question="E con quel budget?", recent=recent, archived=[opening], anchors=[opening], max_chars=8000, archive_chars=2000)
    assert opening in selected
    assert sum(len(item["content"]) for item in conversation_input(selected)) <= 8000
