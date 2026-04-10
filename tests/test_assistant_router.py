import json
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command

from edilcloud.modules.assistant.answer_planner import plan_assistant_answer
from edilcloud.modules.assistant.query_router import classify_assistant_query
from edilcloud.modules.assistant.read_models import build_structured_facts
from edilcloud.modules.assistant.retrieval_service import derive_retrieval_context
from edilcloud.modules.assistant.services import (
    assistant_embedding_label,
    assistant_storage_embedding_dimensions,
    build_project_source_snapshot,
    normalize_embedding_vector,
    retrieve_project_knowledge,
)
from tests.test_projects_api import create_project_fixture, create_workspace_profile


def test_query_router_classifies_team_count_and_timeline_queries():
    team_route = classify_assistant_query("quanti partecipanti ci sono nel progetto?")
    timeline_route = classify_assistant_query("cosa e successo oggi in cantiere?")

    assert team_route.intent == "team_count"
    assert team_route.strategy == "deterministic_db"
    assert timeline_route.intent == "activity_by_date"
    assert timeline_route.temporal_scope == "today"


def test_answer_planner_uses_short_mode_for_count_queries():
    route = classify_assistant_query("quante aziende ci sono nel progetto?")
    plan = plan_assistant_answer(question="quante aziende ci sono nel progetto?", route=route)

    assert plan.target_length == "short"
    assert plan.answer_mode == "fact_list"


def test_retrieval_context_uses_thread_context_for_follow_up_queries():
    route = classify_assistant_query("e per quella task?")
    context = derive_retrieval_context(
        question="e per quella task?",
        route=route,
        thread_metadata={"last_context": {"task_id": 12, "activity_id": 34}},
        recent_messages=[],
    )

    assert context.task_id == 12
    assert context.activity_id == 34
    assert context.context_scope == "activity:34"
    assert context.strict_context is True


@pytest.mark.django_db
def test_retrieve_project_knowledge_uses_deterministic_facts_for_team_queries():
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.router@example.com",
        password="devpass123",
        workspace_name="Assistant Router Workspace",
    )
    project, _task, _activity, _alert_post = create_project_fixture(profile)

    route = classify_assistant_query("quanti partecipanti ci sono nel progetto?")
    structured_facts = build_structured_facts(project=project, route=route, question="quanti partecipanti ci sono nel progetto?")
    source_documents, _current_version = build_project_source_snapshot(project)
    retrieval_context = derive_retrieval_context(
        question="quanti partecipanti ci sono nel progetto?",
        route=route,
        thread_metadata={},
        recent_messages=[],
    )

    bundle = retrieve_project_knowledge(
        project=project,
        query="quanti partecipanti ci sono nel progetto?",
        source_documents=source_documents,
        route=route,
        retrieval_context=retrieval_context,
        structured_facts=structured_facts,
    )

    assert bundle.provider == "deterministic_db"
    assert bundle.citations[0]["source_type"] == "team_directory"
    assert bundle.metrics["result_count"] >= 1


def test_run_assistant_eval_command_reports_dataset_pass_rate():
    dataset_path = Path(__file__).resolve().parent / "data" / "assistant_eval_dataset.json"
    stdout = StringIO()

    call_command("run_assistant_eval", dataset=str(dataset_path), stdout=stdout)
    payload = json.loads(stdout.getvalue())

    assert payload["total"] >= 5
    assert payload["failed"] == 0
    assert payload["pass_rate"] == 100.0


def test_embedding_label_tracks_model_and_dimensions(settings):
    settings.OPENAI_API_KEY = "test-key"
    settings.AI_ASSISTANT_EMBEDDING_MODEL = "text-embedding-3-large"
    settings.AI_ASSISTANT_EMBEDDING_DIMENSIONS = 3072

    assert assistant_embedding_label() == "openai:text-embedding-3-large:3072d"


def test_normalize_embedding_vector_pads_shorter_vectors():
    vector = normalize_embedding_vector([0.5, 0.25, 0.125])

    assert len(vector) == assistant_storage_embedding_dimensions()
    assert vector[:3] == [0.5, 0.25, 0.125]
    assert vector[-1] == 0.0
