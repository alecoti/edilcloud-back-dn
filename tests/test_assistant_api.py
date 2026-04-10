import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from edilcloud.modules.assistant.models import (
    AssistantTone,
    AssistantResponseMode,
    ProjectAssistantChunkMap,
    ProjectAssistantChunkSource,
    ProjectAssistantMessage,
    ProjectAssistantProjectSettings,
    ProjectAssistantRunLog,
    ProjectAssistantUsage,
    ProjectAssistantThread,
)
from edilcloud.modules.assistant.services import (
    RetrievalBundle,
    build_project_source_snapshot,
    get_or_create_project_assistant_state,
    sync_project_assistant_sources,
)
from edilcloud.modules.projects.models import PostAttachment, ProjectMember, ProjectMemberStatus
from edilcloud.modules.workspaces.models import WorkspaceRole
from tests.test_projects_api import auth_headers, create_project_fixture, create_workspace_profile


@pytest.mark.django_db
def test_project_assistant_state_and_ask_routes_work_with_shared_memory(monkeypatch):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.owner@example.com",
        password="devpass123",
        workspace_name="Assistant Workspace",
    )
    project, _task, _activity, _alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="assistant.owner@example.com", password="devpass123")

    retrieval_bundle = RetrievalBundle(
        provider="pgvector",
        profile_static=["Il progetto riguarda il rifacimento facciata con squadra e cronologia condivise."],
        profile_dynamic=["Ultimo aggiornamento: criticita ancoraggio nord e verifica capocantiere."],
        citations=[
            {
                "index": 1,
                "source_key": f"post:{_alert_post.id}",
                "source_type": "post",
                "label": "Criticita ancoraggio nord",
                "score": 0.91,
                "snippet": "Criticita su ancoraggio nord presa in carico e validata.",
                "metadata": {"source_type": "post"},
            }
        ],
        context_markdown="## Project memory profile\n- Rifacimento facciata con forte attenzione agli ancoraggi.",
    )

    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.retrieve_project_knowledge",
        lambda **kwargs: retrieval_bundle,
    )
    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.generate_assistant_completion",
        lambda **kwargs: "Sintesi: oggi il focus e sulla verifica degli ancoraggi nord.",
    )

    state_response = client.get(f"/api/v1/projects/{project.id}/assistant", **headers)
    assert state_response.status_code == 200
    assert state_response.json()["messages"] == []
    assert state_response.json()["active_thread"]["title"] == "Nuova chat"
    assert len(state_response.json()["threads"]) == 1
    assert state_response.json()["stats"]["assistant_ready"] is True
    assert state_response.json()["stats"]["index_status"] in {"indexed", "stale", "processing", "failed"}
    assert state_response.json()["settings"]["effective"]["tone"] == "pragmatico"
    assert state_response.json()["stats"]["token_budget"]["monthly_limit"] >= 100000

    ask_response = client.post(
        f"/api/v1/projects/{project.id}/assistant",
        data=json.dumps({"message": "Dammi una sintesi del progetto"}),
        content_type="application/json",
        **headers,
    )
    assert ask_response.status_code == 201
    ask_payload = ask_response.json()
    assert ask_payload["user_message"]["content"] == "Dammi una sintesi del progetto"
    assert ask_payload["thread"]["title"] == "Dammi una sintesi del progetto"
    assert ask_payload["assistant_message"]["content"].startswith("Sintesi:")
    assert ask_payload["assistant_message"]["citations"][0]["label"] == "Criticita ancoraggio nord"
    assert ask_payload["stats"]["assistant_ready"] is True
    assert ask_payload["stats"]["token_budget"]["monthly_used"] > 0
    assert ask_payload["assistant_message"]["metadata"]["token_usage"]["total_tokens"] > 0
    assert ProjectAssistantUsage.objects.filter(project=project, profile=profile).count() == 1
    run_log = ProjectAssistantRunLog.objects.get(project=project, profile=profile)
    assert run_log.intent == "project_summary"
    assert run_log.retrieval_provider == "pgvector"
    assert run_log.top_results[0]["label"] == "Criticita ancoraggio nord"

    refreshed_state_response = client.get(f"/api/v1/projects/{project.id}/assistant", **headers)
    assert refreshed_state_response.status_code == 200
    refreshed_messages = refreshed_state_response.json()["messages"]
    assert len(refreshed_messages) == 2
    assert refreshed_messages[0]["role"] == "user"
    assert refreshed_messages[1]["role"] == "assistant"
    assert refreshed_state_response.json()["active_thread"]["message_count"] == 2


@pytest.mark.django_db
def test_project_assistant_threads_can_be_created_and_messages_stay_isolated(monkeypatch):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.threads@example.com",
        password="devpass123",
        workspace_name="Assistant Threads Workspace",
    )
    project, _task, _activity, alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="assistant.threads@example.com", password="devpass123")

    retrieval_bundle = RetrievalBundle(
        provider="pgvector",
        profile_static=["Progetto demo con memoria condivisa."],
        profile_dynamic=["Ultima nota: criticita locale su ancoraggi."],
        citations=[
            {
                "index": 1,
                "source_key": f"post:{alert_post.id}",
                "source_type": "post",
                "label": "Criticita ancoraggio nord",
                "score": 0.91,
                "snippet": "Criticita su ancoraggio nord presa in carico e validata.",
                "metadata": {"source_type": "post"},
            }
        ],
        context_markdown="## Project memory profile\n- Criticita su ancoraggio nord.",
    )

    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.retrieve_project_knowledge",
        lambda **kwargs: retrieval_bundle,
    )
    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.generate_assistant_completion",
        lambda **kwargs: "Risposta thread-aware.",
    )

    create_thread_response = client.post(
        f"/api/v1/projects/{project.id}/assistant/threads",
        data=json.dumps({"title": "Coordinamento sicurezza"}),
        content_type="application/json",
        **headers,
    )
    assert create_thread_response.status_code == 201
    thread_payload = create_thread_response.json()
    thread_id = thread_payload["thread"]["id"]
    assert thread_payload["thread"]["title"] == "Coordinamento sicurezza"

    ask_response = client.post(
        f"/api/v1/projects/{project.id}/assistant",
        data=json.dumps({"message": "Dimmi il punto sulla sicurezza", "thread_id": thread_id}),
        content_type="application/json",
        **headers,
    )
    assert ask_response.status_code == 201
    assert ask_response.json()["thread"]["id"] == thread_id

    state_response = client.get(
        f"/api/v1/projects/{project.id}/assistant?thread_id={thread_id}",
        **headers,
    )
    assert state_response.status_code == 200
    assert state_response.json()["active_thread_id"] == thread_id
    assert len(state_response.json()["messages"]) == 2
    assert {message["thread_id"] for message in state_response.json()["messages"]} == {thread_id}

    assert not ProjectAssistantMessage.objects.filter(project=project).exclude(thread_id=thread_id).exists()


@pytest.mark.django_db
def test_project_assistant_threads_are_isolated_per_profile(monkeypatch):
    client = Client()
    _owner_user, _workspace, owner_profile = create_workspace_profile(
        email="assistant.owner-two@example.com",
        password="devpass123",
        workspace_name="Assistant Isolation Workspace",
    )
    collaborator_user, _collaborator_workspace, collaborator_profile = create_workspace_profile(
        email="assistant.collaborator@example.com",
        password="devpass123",
        workspace_name="Collaborator Workspace",
    )
    project, _task, _activity, alert_post = create_project_fixture(owner_profile)
    ProjectMember.objects.create(
        project=project,
        profile=collaborator_profile,
        role=WorkspaceRole.MANAGER,
        status=ProjectMemberStatus.ACTIVE,
    )
    owner_headers = auth_headers(
        client,
        email="assistant.owner-two@example.com",
        password="devpass123",
    )
    collaborator_headers = auth_headers(
        client,
        email=collaborator_user.email,
        password="devpass123",
    )

    retrieval_bundle = RetrievalBundle(
        provider="pgvector",
        profile_static=["Cantiere condiviso con thread privati per utente."],
        profile_dynamic=["Ultima nota: coordinamento accessi lato nord."],
        citations=[
            {
                "index": 1,
                "source_key": f"post:{alert_post.id}",
                "source_type": "post",
                "label": "Criticita ancoraggio nord",
                "score": 0.88,
                "snippet": "Criticita lato nord sotto osservazione.",
                "metadata": {"source_type": "post"},
            }
        ],
        context_markdown="## Project memory profile\n- Cantiere condiviso con note separate per utente.",
    )

    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.retrieve_project_knowledge",
        lambda **kwargs: retrieval_bundle,
    )
    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.generate_assistant_completion",
        lambda **kwargs: "Risposta privata per utente.",
    )

    owner_thread = client.post(
        f"/api/v1/projects/{project.id}/assistant/threads",
        data=json.dumps({"title": "Thread owner"}),
        content_type="application/json",
        **owner_headers,
    )
    assert owner_thread.status_code == 201
    owner_thread_id = owner_thread.json()["thread"]["id"]

    collaborator_thread = client.post(
        f"/api/v1/projects/{project.id}/assistant/threads",
        data=json.dumps({"title": "Thread collaborator"}),
        content_type="application/json",
        **collaborator_headers,
    )
    assert collaborator_thread.status_code == 201
    collaborator_thread_id = collaborator_thread.json()["thread"]["id"]

    owner_state = client.get(
        f"/api/v1/projects/{project.id}/assistant?thread_id={owner_thread_id}",
        **owner_headers,
    )
    collaborator_state = client.get(
        f"/api/v1/projects/{project.id}/assistant?thread_id={collaborator_thread_id}",
        **collaborator_headers,
    )

    assert owner_state.status_code == 200
    assert collaborator_state.status_code == 200
    assert {thread["id"] for thread in owner_state.json()["threads"]} == {owner_thread_id}
    assert {thread["id"] for thread in collaborator_state.json()["threads"]} == {collaborator_thread_id}
    assert ProjectAssistantThread.objects.filter(project=project, author=owner_profile).count() == 1


@pytest.mark.django_db
def test_structured_assistant_queries_bypass_llm_and_return_deterministic_answer(monkeypatch):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.deterministic@example.com",
        password="devpass123",
        workspace_name="Assistant Deterministic Workspace",
    )
    project, _task, _activity, _alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="assistant.deterministic@example.com", password="devpass123")

    def fail_generation(**_kwargs):
        raise AssertionError("LLM generation should not be used for deterministic_db queries")

    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.generate_assistant_completion",
        fail_generation,
    )

    ask_response = client.post(
        f"/api/v1/projects/{project.id}/assistant",
        data=json.dumps({"message": "quanti partecipanti ci sono nel progetto?"}),
        content_type="application/json",
        **headers,
    )

    assert ask_response.status_code == 201
    payload = ask_response.json()
    assert "Totale partecipanti attivi" in payload["assistant_message"]["content"]
    assert payload["assistant_message"]["content"].count("Totale partecipanti attivi") == 1
    assert payload["assistant_message"]["metadata"]["strategy"] == "deterministic_db"
    run_log = ProjectAssistantRunLog.objects.get(project=project, profile=profile)
    assert run_log.intent == "team_count"
    assert run_log.strategy == "deterministic_db"
    assert run_log.response_length_mode == "short"


@pytest.mark.django_db
def test_assistant_quality_report_command_aggregates_persisted_metadata():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.quality@example.com",
        password="devpass123",
        workspace_name="Assistant Quality Workspace",
    )
    project, _task, _activity, _alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="assistant.quality@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/projects/{project.id}/assistant",
        data=json.dumps({"message": "quanti partecipanti ci sono nel progetto?"}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 201

    stdout = StringIO()
    call_command("run_assistant_quality_report", limit=50, stdout=stdout)
    report = json.loads(stdout.getvalue())

    assert report["analyzed_messages"] >= 1
    assert "team_count" in report["success_rate_per_intent"]


@pytest.mark.django_db
def test_assistant_quality_gate_command_passes_for_green_dataset_and_run_logs():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.gate@example.com",
        password="devpass123",
        workspace_name="Assistant Gate Workspace",
    )
    project, _task, _activity, _alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="assistant.gate@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/projects/{project.id}/assistant",
        data=json.dumps({"message": "quanti partecipanti ci sono nel progetto?"}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 201

    stdout = StringIO()
    call_command(
        "run_assistant_quality_gate",
        limit=50,
        min_pass_rate=100.0,
        min_supported_rate=90.0,
        min_topical_rate=90.0,
        min_grounding=0.1,
        max_mismatch=0.25,
        stdout=stdout,
    )
    payload = json.loads(stdout.getvalue())

    assert payload["gate"]["ok"] is True
    assert payload["gate"]["checks"]["dataset_pass_rate"] is True
    assert payload["gate"]["checks"]["supported_rate"] is True


@pytest.mark.django_db
def test_project_assistant_settings_patch_updates_defaults_and_project_overrides():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.settings@example.com",
        password="devpass123",
        workspace_name="Assistant Settings Workspace",
    )
    project, _task, _activity, _alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="assistant.settings@example.com", password="devpass123")

    defaults_response = client.patch(
        f"/api/v1/projects/{project.id}/assistant/settings",
        data=json.dumps(
            {
                "scope": "defaults",
                "tone": "discorsivo",
                "response_mode": "timeline",
                "citation_mode": "dettagliato",
                "custom_instructions": "Chiudi sempre con un prossimo passo pratico.",
                "preferred_model": "gpt-4.1-mini",
                "monthly_token_limit": 250000,
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert defaults_response.status_code == 200
    defaults_payload = defaults_response.json()
    assert defaults_payload["settings"]["defaults"]["tone"] == "discorsivo"
    assert defaults_payload["settings"]["defaults"]["monthly_token_limit"] == 250000
    assert defaults_payload["settings"]["effective"]["response_mode"] == "timeline"
    assert defaults_payload["settings"]["effective"]["preferred_model"] == "gpt-4.1-mini"
    assert defaults_payload["token_budget"]["monthly_limit"] >= 100000

    project_response = client.patch(
        f"/api/v1/projects/{project.id}/assistant/settings",
        data=json.dumps(
            {
                "scope": "project",
                "tone": "tecnico",
                "response_mode": "checklist",
            }
        ),
        content_type="application/json",
        **headers,
    )
    assert project_response.status_code == 200
    project_payload = project_response.json()
    assert project_payload["settings"]["project"]["has_overrides"] is True
    assert project_payload["settings"]["effective"]["tone"] == "tecnico"
    assert project_payload["settings"]["effective"]["response_mode"] == "checklist"
    assert project_payload["settings"]["effective"]["citation_mode"] == "dettagliato"

    override = ProjectAssistantProjectSettings.objects.get(project=project, profile=profile)
    assert override.tone == AssistantTone.TECNICO
    assert override.response_mode == AssistantResponseMode.CHECKLIST


@pytest.mark.django_db
def test_project_assistant_settings_remain_isolated_per_profile():
    client = Client()
    _owner_user, _workspace, owner_profile = create_workspace_profile(
        email="assistant.settings.owner@example.com",
        password="devpass123",
        workspace_name="Assistant Settings Isolation Workspace",
    )
    _collaborator_user, _collaborator_workspace, collaborator_profile = create_workspace_profile(
        email="assistant.settings.collaborator@example.com",
        password="devpass123",
        workspace_name="Assistant Settings Collaborator Workspace",
    )
    project, _task, _activity, _alert_post = create_project_fixture(owner_profile)
    ProjectMember.objects.create(
        project=project,
        profile=collaborator_profile,
        role=WorkspaceRole.MANAGER,
        status=ProjectMemberStatus.ACTIVE,
    )

    owner_headers = auth_headers(
        client,
        email="assistant.settings.owner@example.com",
        password="devpass123",
    )
    collaborator_headers = auth_headers(
        client,
        email="assistant.settings.collaborator@example.com",
        password="devpass123",
    )

    owner_response = client.patch(
        f"/api/v1/projects/{project.id}/assistant/settings",
        data=json.dumps(
            {
                "scope": "defaults",
                "tone": "tecnico",
                "response_mode": "timeline",
                "citation_mode": "dettagliato",
                "custom_instructions": "Chiudi con rischi e prossimi passi.",
            }
        ),
        content_type="application/json",
        **owner_headers,
    )
    assert owner_response.status_code == 200

    owner_project_response = client.patch(
        f"/api/v1/projects/{project.id}/assistant/settings",
        data=json.dumps(
            {
                "scope": "project",
                "tone": "discorsivo",
                "response_mode": "checklist",
            }
        ),
        content_type="application/json",
        **owner_headers,
    )
    assert owner_project_response.status_code == 200

    collaborator_state = client.get(
        f"/api/v1/projects/{project.id}/assistant",
        **collaborator_headers,
    )
    assert collaborator_state.status_code == 200
    collaborator_settings = collaborator_state.json()["settings"]

    assert collaborator_settings["defaults"]["tone"] == "pragmatico"
    assert collaborator_settings["effective"]["tone"] == "pragmatico"
    assert collaborator_settings["effective"]["response_mode"] == "auto"
    assert collaborator_settings["project"]["has_overrides"] is False
    assert not ProjectAssistantProjectSettings.objects.filter(
        project=project,
        profile=collaborator_profile,
    ).exists()


@pytest.mark.django_db
def test_project_drafting_context_route_returns_pgvector_brief(monkeypatch):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.drafting@example.com",
        password="devpass123",
        workspace_name="Drafting Workspace",
    )
    project, task, activity, _alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="assistant.drafting@example.com", password="devpass123")

    retrieval_bundle = RetrievalBundle(
        provider="pgvector",
        profile_static=["Residenza con lavorazioni facciata e verbali gia presenti."],
        profile_dynamic=["Memoria recente: sopralluogo su ancoraggi e coordinamento marciapiede."],
        citations=[
            {
                "index": 1,
                "source_key": f"activity:{activity.id}",
                "source_type": "activity",
                "label": activity.title,
                "score": 0.88,
                "snippet": "Preparazione canaline e verifica percorso operativo.",
                "metadata": {"source_type": "activity"},
            }
        ],
        context_markdown="## Project memory profile\n- Verbali e aggiornamenti recenti gia consolidati in memoria.",
    )

    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.retrieve_project_knowledge",
        lambda **kwargs: retrieval_bundle,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/assistant/drafting-context",
        data=json.dumps(
            {
                "document_type": "rapportino",
                "locale": "it",
                "task_id": task.id,
                "task_name": task.name,
                "activity_id": activity.id,
                "activity_title": activity.title,
                "notes": "Controllare avanzamento e criticita residue.",
                "voice_italian": "La squadra ha completato la verifica finale.",
                "evidence_excerpts": ["Verifica ancoraggi completata senza ulteriori anomalie."],
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "pgvector"
    assert "Memory brief" in payload["context_markdown"]
    assert payload["sources"][0]["label"] == activity.title


@pytest.mark.django_db
def test_project_assistant_stream_route_emits_native_sse_events(monkeypatch):
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.stream@example.com",
        password="devpass123",
        workspace_name="Assistant Stream Workspace",
    )
    project, _task, _activity, _alert_post = create_project_fixture(profile)
    headers = auth_headers(client, email="assistant.stream@example.com", password="devpass123")

    retrieval_bundle = RetrievalBundle(
        provider="pgvector",
        profile_static=["Cantiere facciata con documentazione e criticita recenti."],
        profile_dynamic=["Ancoraggi nord verificati in giornata."],
        citations=[
            {
                "index": 1,
                "source_key": f"post:{_alert_post.id}",
                "source_type": "post",
                "label": "Criticita ancoraggio nord",
                "score": 0.93,
                "snippet": "Verifica finale eseguita sugli ancoraggi nord.",
                "metadata": {"source_type": "post"},
            }
        ],
        context_markdown="## Project memory profile\n- Evidenze recenti su ancoraggi e coordinamento squadra.",
    )

    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.retrieve_project_knowledge",
        lambda **kwargs: retrieval_bundle,
    )
    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.generate_assistant_completion",
        lambda **kwargs: "Sintesi operativa: ancoraggi nord verificati e criticita sotto controllo.",
    )
    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.iter_openai_assistant_text",
        lambda **kwargs: iter(
            [
                "Sintesi operativa: ",
                "ancoraggi nord verificati ",
                "e criticita sotto controllo.",
            ]
        ),
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/assistant/stream",
        data=json.dumps({"message": "Dammi il punto sugli ancoraggi nord"}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/event-stream")
    payload = b"".join(response.streaming_content).decode("utf-8")
    assert "event: meta" in payload
    assert "event: delta" in payload
    assert "event: done" in payload
    assert "ancoraggi nord verificati" in payload


@pytest.mark.django_db
def test_pgvector_sync_is_incremental_and_tracks_real_file_backed_sources(monkeypatch):
    _user, _workspace, profile = create_workspace_profile(
        email="assistant.sync@example.com",
        password="devpass123",
        workspace_name="Assistant Sync Workspace",
    )
    project, _task, _activity, alert_post = create_project_fixture(profile)
    PostAttachment.objects.create(
        post=alert_post,
        file=SimpleUploadedFile("nota-vocale.mp3", b"ID3demo-audio", content_type="audio/mpeg"),
    )

    monkeypatch.setattr("edilcloud.modules.assistant.services.assistant_rag_enabled", lambda: True)
    monkeypatch.setattr(
        "edilcloud.modules.assistant.services.embed_texts",
        lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts],
    )

    state = get_or_create_project_assistant_state(project)
    source_documents, current_version = build_project_source_snapshot(project)
    sync_project_assistant_sources(
        project=project,
        state=state,
        source_documents=source_documents,
        current_version=current_version,
        force=True,
    )

    assert ProjectAssistantChunkSource.objects.filter(
        assistant_state=state,
        scope="project",
    ).exists()
    chunk_maps = ProjectAssistantChunkMap.objects.filter(assistant_state=state, scope="project")
    assert chunk_maps.exists()
    indexed_file_names = {
        str(name or "")
        for name in chunk_maps.values_list("file_name", flat=True)
        if name
    }
    assert any(name.startswith("verbale-01") and name.endswith(".pdf") for name in indexed_file_names)
    assert any(name.startswith("tavola") and name.endswith(".png") for name in indexed_file_names)
    assert any(name.startswith("nota-vocale") and name.endswith(".mp3") for name in indexed_file_names)
    pdf_chunks = list(chunk_maps.filter(file_name__startswith="verbale-01"))
    assert pdf_chunks
    assert all(
        chunk.extraction_status == str((chunk.metadata_snapshot or {}).get("extraction_status") or "")
        for chunk in pdf_chunks
    )

    initial_chunk_point_ids = set(chunk_maps.values_list("point_id", flat=True))
    initial_alert_point_ids = set(
        chunk_maps.filter(source_key=f"post:{alert_post.id}").values_list("point_id", flat=True)
    )
    initial_chunk_count = chunk_maps.count()

    sync_project_assistant_sources(
        project=project,
        state=state,
        source_documents=source_documents,
        current_version=current_version,
        force=False,
    )
    assert set(chunk_maps.values_list("point_id", flat=True)) == initial_chunk_point_ids
    assert chunk_maps.count() == initial_chunk_count

    alert_post.text = "Criticita ancoraggio nord aggiornata dopo verifica finale"
    alert_post.original_text = alert_post.text
    alert_post.save()
    updated_source_documents, updated_version = build_project_source_snapshot(project)
    sync_project_assistant_sources(
        project=project,
        state=state,
        source_documents=updated_source_documents,
        current_version=updated_version,
        force=False,
    )
    refreshed_chunk_maps = ProjectAssistantChunkMap.objects.filter(assistant_state=state, scope="project")
    refreshed_alert_point_ids = set(
        refreshed_chunk_maps.filter(source_key=f"post:{alert_post.id}").values_list("point_id", flat=True)
    )
    refreshed_chunk_point_ids = set(refreshed_chunk_maps.values_list("point_id", flat=True))
    assert refreshed_alert_point_ids
    assert refreshed_alert_point_ids != initial_alert_point_ids
    assert initial_alert_point_ids.isdisjoint(refreshed_alert_point_ids)
    changed_point_ids = refreshed_chunk_point_ids.symmetric_difference(initial_chunk_point_ids)
    assert changed_point_ids
    assert changed_point_ids.issuperset(initial_alert_point_ids | refreshed_alert_point_ids)
    assert len(changed_point_ids) < len(refreshed_chunk_point_ids)
