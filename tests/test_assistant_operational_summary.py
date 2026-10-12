from datetime import timedelta
import json

import pytest
from django.test import Client
from django.utils import timezone

from edilcloud.modules.assistant.query_router import classify_assistant_query
from edilcloud.modules.assistant.read_models import build_project_summary_facts
from edilcloud.modules.assistant.models import ProjectAssistantRunLog
from edilcloud.modules.assistant.retrieval_service import AssistantRetrievalContext
from edilcloud.modules.assistant.services import (
    RetrievalBundle,
    build_assistant_prompt,
    build_project_source_snapshot,
    ensure_default_assistant_thread,
    retrieve_project_knowledge,
)
from edilcloud.modules.projects.models import PostKind, ProjectDocument, ProjectPost
from tests.test_assistant_eval import resolved_settings
from tests.test_projects_api import auth_headers, create_project_fixture, create_workspace_profile


@pytest.mark.django_db
def test_operational_summary_counts_all_alerts_and_marks_old_records_as_unconfirmed():
    _user, _workspace, profile = create_workspace_profile(
        email="operational.summary@example.com",
        password="devpass123",
    )
    project, task, activity, _first_alert = create_project_fixture(profile)
    for index in range(6):
        ProjectPost.objects.create(
            project=project,
            task=task,
            activity=activity,
            author=profile,
            post_kind=PostKind.ISSUE,
            text=f"Segnalazione aperta {index + 1}",
            alert=True,
        )

    brief = build_project_summary_facts(project, now=timezone.now() + timedelta(days=30))

    assert brief.facts["open_alert_count"] == 7
    assert brief.facts["task_overdue_count"] == 1
    assert brief.facts["activity_in_progress_count"] == 1
    assert brief.facts["stale"] is True
    assert len([citation for citation in brief.citations if citation["source_type"] == "post"]) == 3
    assert any("stato odierno" in section for section in brief.sections)
    assert any("Montaggio campata A" in section for section in brief.sections)
    assert brief.citations[0]["metadata"]["provenance"] == "structured_db"
    assert all(citation["metadata"]["project_id"] == project.id for citation in brief.citations)


@pytest.mark.django_db
def test_recent_document_does_not_hide_stale_operational_state():
    _user, _workspace, profile = create_workspace_profile(
        email="operational.freshness@example.com",
        password="devpass123",
    )
    project, task, activity, _alert_post = create_project_fixture(profile)
    old_timestamp = timezone.now() - timedelta(days=45)
    task.__class__.objects.filter(pk=task.pk).update(updated_at=old_timestamp)
    activity.__class__.objects.filter(pk=activity.pk).update(updated_at=old_timestamp)
    ProjectPost.objects.filter(project=project).update(updated_at=old_timestamp, published_date=old_timestamp)
    ProjectDocument.objects.create(project=project, title="Verbale appena caricato", document="reports/latest.pdf")

    brief = build_project_summary_facts(project)

    assert brief.facts["document_count"] == 2
    assert brief.facts["stale"] is True
    assert brief.facts["days_since_update"] >= 44
    assert not any("Verbale appena caricato" in section for section in brief.sections)


@pytest.mark.django_db
def test_edit_to_older_issue_counts_as_latest_operational_update():
    _user, _workspace, profile = create_workspace_profile(
        email="operational.edited.issue@example.com",
        password="devpass123",
    )
    project, task, activity, issue = create_project_fixture(profile)
    old_timestamp = timezone.now() - timedelta(days=45)
    task.__class__.objects.filter(pk=task.pk).update(updated_at=old_timestamp)
    activity.__class__.objects.filter(pk=activity.pk).update(updated_at=old_timestamp)
    ProjectPost.objects.filter(project=project).update(updated_at=old_timestamp, published_date=old_timestamp)
    recent_edit = timezone.now()
    ProjectPost.objects.filter(pk=issue.pk).update(updated_at=recent_edit)

    brief = build_project_summary_facts(project, now=recent_edit + timedelta(days=1))

    assert brief.facts["stale"] is False
    assert brief.facts["days_since_update"] == 1
    assert brief.facts["last_operational_update"] == recent_edit.isoformat()


@pytest.mark.django_db
def test_summary_retrieval_keeps_database_snapshot_and_numbered_evidence(monkeypatch):
    _user, _workspace, profile = create_workspace_profile(
        email="operational.evidence@example.com",
        password="devpass123",
    )
    project, _task, _activity, alert_post = create_project_fixture(profile)
    route = classify_assistant_query("Mi fai un riassunto del cantiere?")
    facts = build_project_summary_facts(project)
    sources, _version = build_project_source_snapshot(project)
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)

    bundle = retrieve_project_knowledge(
        project=project,
        query="Mi fai un riassunto del cantiere?",
        source_documents=sources,
        route=route,
        structured_facts=facts,
    )

    assert bundle.citations[0]["source_key"] == f"project:{project.id}"
    assert any(citation["source_key"] == f"post:{alert_post.id}" for citation in bundle.citations)
    assert "[1] [project]" in bundle.context_markdown
    assert "Segnalazioni marcate aperte" in bundle.context_markdown or "segnalazioni marcate aperte" in bundle.context_markdown
    assert bundle.metrics["structured_anchor_count"] >= 2
    assert all(citation["metadata"].get("project_id") == project.id for citation in bundle.citations)


@pytest.mark.django_db
def test_default_summary_uses_structured_evidence_without_embedding_or_search(monkeypatch, settings):
    _user, _workspace, profile = create_workspace_profile(
        email="operational.direct@example.com",
        password="devpass123",
    )
    project, _task, _activity, alert_post = create_project_fixture(profile)
    route = classify_assistant_query("Mi fai un riassunto del cantiere?")
    facts = build_project_summary_facts(project)
    sources, _version = build_project_source_snapshot(project)
    settings.AI_ASSISTANT_SUMMARY_GENERATION_ENABLED = False
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: True)

    def unexpected_search(*args, **kwargs):
        raise AssertionError("The default structured summary must not run semantic or local search")

    monkeypatch.setattr("edilcloud.modules.assistant.services.build_local_retrieval_bundle", unexpected_search)
    monkeypatch.setattr("edilcloud.modules.assistant.services.build_pgvector_retrieval_bundle", unexpected_search)
    monkeypatch.setattr("edilcloud.modules.assistant.services.embed_texts", unexpected_search)

    bundle = retrieve_project_knowledge(
        project=project,
        query="Mi fai un riassunto del cantiere?",
        source_documents=sources,
        route=route,
        structured_facts=facts,
    )

    assert bundle.provider == "deterministic_db"
    assert bundle.metrics["direct_summary"] is True
    assert bundle.metrics["embedding_latency_ms"] == 0
    assert bundle.citations[0]["source_key"] == f"project:{project.id}"
    assert any(citation["source_key"] == f"post:{alert_post.id}" for citation in bundle.citations)
    assert [citation["index"] for citation in bundle.citations] == list(range(1, len(bundle.citations) + 1))


@pytest.mark.django_db
@pytest.mark.parametrize("generation_enabled,strict_context", [(True, False), (False, True)])
def test_summary_retains_hybrid_retrieval_for_experiments_and_scoped_questions(
    monkeypatch, settings, generation_enabled, strict_context
):
    _user, _workspace, profile = create_workspace_profile(
        email=f"operational.hybrid.{generation_enabled}.{strict_context}@example.com",
        password="devpass123",
    )
    project, task, _activity, _alert_post = create_project_fixture(profile)
    route = classify_assistant_query("Mi fai un riassunto del cantiere?")
    facts = build_project_summary_facts(project)
    sources, _version = build_project_source_snapshot(project)
    settings.AI_ASSISTANT_SUMMARY_GENERATION_ENABLED = generation_enabled
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: True)
    calls = []

    def fake_pgvector(**kwargs):
        calls.append(kwargs["query"])
        return RetrievalBundle(
            provider="pgvector",
            profile_static=[],
            profile_dynamic=[],
            citations=[],
            context_markdown="",
            metrics={},
        )

    monkeypatch.setattr("edilcloud.modules.assistant.services.build_pgvector_retrieval_bundle", fake_pgvector)
    context = (
        AssistantRetrievalContext(task_id=task.id, context_scope="task", strict_context=True)
        if strict_context else None
    )

    bundle = retrieve_project_knowledge(
        project=project,
        query="Mi fai un riassunto del cantiere?",
        source_documents=sources,
        route=route,
        retrieval_context=context,
        structured_facts=facts,
    )

    assert calls == ["Mi fai un riassunto del cantiere?"]
    assert bundle.provider == "pgvector"
    assert bundle.metrics.get("direct_summary") is not True
    if strict_context:
        assert bundle.metrics["context_scope"] == "task"
        assert not any(citation["source_type"] == "project" for citation in bundle.citations)
    else:
        assert bundle.citations[0]["source_key"] == f"project:{project.id}"


@pytest.mark.django_db
def test_summary_prompt_requires_freshness_and_operational_state(monkeypatch):
    _user, _workspace, profile = create_workspace_profile(
        email="operational.prompt@example.com",
        password="devpass123",
    )
    project, _task, _activity, _alert_post = create_project_fixture(profile)
    route = classify_assistant_query("Mi fai un riassunto del cantiere?")
    facts = build_project_summary_facts(project)
    sources, _version = build_project_source_snapshot(project)
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)
    bundle = retrieve_project_knowledge(
        project=project,
        query="Mi fai un riassunto del cantiere?",
        source_documents=sources,
        route=route,
        structured_facts=facts,
    )

    system_prompt, user_prompt = build_assistant_prompt(
        project=project,
        thread=ensure_default_assistant_thread(project, profile),
        question="Mi fai un riassunto del cantiere?",
        retrieval_query="Mi fai un riassunto del cantiere?",
        retrieval_bundle=bundle,
        recent_messages=[],
        resolved_settings=resolved_settings(),
        route=route,
        structured_facts=facts,
    )

    assert "operational site update" in system_prompt
    assert "last operational update" in system_prompt
    assert "STRUCTURED_FACTS:" in user_prompt
    assert "[1] [project]" in user_prompt


@pytest.mark.django_db
@pytest.mark.parametrize("stream", [False, True])
def test_summary_without_provider_returns_cited_operational_brief(monkeypatch, settings, stream):
    settings.OPENAI_API_KEY = ""
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email=f"operational.http.{stream}@example.com",
        password="devpass123",
    )
    project, _task, _activity, alert_post = create_project_fixture(profile)
    alert_post.text = (
        "Criticita su ancoraggio nord. Il fissaggio deve essere verificato prima del collaudo. "
        "Prossimo passo: predisporre una riunione generica."
    )
    alert_post.save(update_fields=["text"])
    headers = auth_headers(client, email=f"operational.http.{stream}@example.com", password="devpass123")
    endpoint = f"/api/v1/projects/{project.id}/assistant"
    if stream:
        endpoint += "/stream"

    response = client.post(
        endpoint,
        data=json.dumps({"message": "Mi fai un riassunto del cantiere?"}),
        content_type="application/json",
        **headers,
    )
    if stream:
        assert response.status_code == 200
        events = b"".join(response.streaming_content).decode("utf-8")
        assert "event: done" in events
        payload = json.loads(events.split("event: done\ndata: ", 1)[1].split("\n\n", 1)[0])
    else:
        assert response.status_code == 201
        payload = response.json()

    message = payload["assistant_message"]
    content = message["content"]
    assert project.name in content
    assert "Ultimo aggiornamento operativo" in content
    assert "oltre la data pianificata" in content
    assert "segnalazioni marcate aperte" in content
    assert "Il fissaggio deve essere verificato prima del collaudo" in content
    assert "Prossimo passo" not in content
    assert "Non sono riuscito a usare il modello" not in content
    assert "[1]" in content
    cited_keys = {citation["source_key"] for citation in message["citations"]}
    assert f"project:{project.id}" in cited_keys
    assert f"post:{alert_post.id}" in cited_keys


@pytest.mark.django_db
def test_summary_prioritizes_issues_over_newer_documentation_alerts():
    _user, _workspace, profile = create_workspace_profile(
        email="operational.issue.priority@example.com",
        password="devpass123",
    )
    project, task, activity, issue = create_project_fixture(profile)
    ProjectPost.objects.create(
        project=project,
        task=task,
        activity=activity,
        author=profile,
        post_kind=PostKind.DOCUMENTATION,
        text="Nota di coordinamento documentale",
        alert=True,
    )

    brief = build_project_summary_facts(project)

    assert brief.facts["open_alert_count"] == 2
    assert brief.citations[1]["source_key"] == f"post:{issue.id}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("model_answer", "gate_reason"),
    [
        ("Le lavorazioni sono tutte in corso.", "missing_citations"),
        ("Stato operativo [1]. Dettaglio inventato [99].", "invalid_citations"),
        ("Segnalazione ancora aperta [2].", "missing_project_snapshot_citation"),
        ("Stato registrato [1]. Criticita sugli ancoraggi [2].", "passed"),
    ],
)
def test_summary_generation_accepts_only_cited_project_answers(
    monkeypatch, settings, model_answer, gate_reason
):
    settings.OPENAI_API_KEY = "test-key"
    settings.AI_ASSISTANT_SUMMARY_GENERATION_ENABLED = True
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)
    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.generate_assistant_completion",
        lambda **kwargs: model_answer,
    )
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email=f"operational.gate.{gate_reason}@example.com",
        password="devpass123",
    )
    project, _task, _activity, _issue = create_project_fixture(profile)
    headers = auth_headers(client, email=f"operational.gate.{gate_reason}@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/projects/{project.id}/assistant",
        data=json.dumps({"message": "Mi fai un riassunto del cantiere?"}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 201
    content = response.json()["assistant_message"]["content"]
    run_log = ProjectAssistantRunLog.objects.get(project=project)
    assert run_log.retrieval_metrics["summary_answer_gate"] == gate_reason
    if gate_reason == "passed":
        assert content == model_answer
    else:
        assert "Ultimo aggiornamento operativo" in content
        assert model_answer not in content


@pytest.mark.django_db
def test_streamed_summary_does_not_expose_rejected_model_text(monkeypatch, settings):
    settings.OPENAI_API_KEY = "test-key"
    settings.AI_ASSISTANT_SUMMARY_GENERATION_ENABLED = True
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)
    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.generate_assistant_completion",
        lambda **kwargs: "Stato senza fonti e non verificato.",
    )
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="operational.gate.stream@example.com",
        password="devpass123",
    )
    project, _task, _activity, _issue = create_project_fixture(profile)
    headers = auth_headers(client, email="operational.gate.stream@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/projects/{project.id}/assistant/stream",
        data=json.dumps({"message": "Mi fai un riassunto del cantiere?"}),
        content_type="application/json",
        **headers,
    )
    events = b"".join(response.streaming_content).decode("utf-8")

    assert response.status_code == 200
    assert "event: done" in events
    assert "Stato senza fonti" not in events
    assert "Ultimo aggiornamento operativo" in events
    assert ProjectAssistantRunLog.objects.get(project=project).retrieval_metrics["summary_answer_gate"] == "missing_citations"


@pytest.mark.django_db
@pytest.mark.parametrize("stream", [False, True])
def test_default_summary_policy_uses_brief_without_generation(monkeypatch, settings, stream):
    settings.OPENAI_API_KEY = "test-key"
    settings.AI_ASSISTANT_CONVERSATIONAL_ENABLED = False
    settings.AI_ASSISTANT_SUMMARY_GENERATION_ENABLED = False
    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: False)

    def reject_generation(**kwargs):
        raise AssertionError("The summary policy must not call the model")

    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.generate_assistant_completion",
        reject_generation,
    )
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email=f"operational.policy.{stream}@example.com",
        password="devpass123",
    )
    project, _task, _activity, _issue = create_project_fixture(profile)
    headers = auth_headers(client, email=f"operational.policy.{stream}@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/projects/{project.id}/assistant{'/stream' if stream else ''}",
        data=json.dumps({"message": "Mi fai un riassunto del cantiere?"}),
        content_type="application/json",
        **headers,
    )
    if stream:
        events = b"".join(response.streaming_content).decode("utf-8")
        assert "event: done" in events
        assert "Ultimo aggiornamento operativo" in events
    else:
        assert response.status_code == 201
        assert "Ultimo aggiornamento operativo" in response.json()["assistant_message"]["content"]
    run_log = ProjectAssistantRunLog.objects.get(project=project)
    assert run_log.retrieval_metrics["summary_answer_gate"] == "deterministic_policy"
    assert run_log.assistant_message.metadata["summary_answer_gate"] == "deterministic_policy"
