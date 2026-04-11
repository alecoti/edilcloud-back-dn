from __future__ import annotations

from typing import Any

from django.http import StreamingHttpResponse
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from edilcloud.modules.assistant.document_drafting import (
    autocomplete_project_document_draft,
    generate_project_document_draft,
    translate_project_document_text,
)
from edilcloud.modules.assistant.services import (
    ask_project_assistant,
    create_assistant_thread_for_project,
    get_project_assistant_state,
    get_project_drafting_context,
    iter_project_assistant_events,
    prepare_project_assistant_run,
    update_project_assistant_settings,
)
from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.modules.projects.api import current_profile


auth = JWTAuth()
router = Router(tags=["assistant"])


class AskProjectAssistantRequestSchema(Schema):
    message: str
    force_sync: bool = False
    thread_id: int | None = None
    task_id: int | None = None
    activity_id: int | None = None


class CreateAssistantThreadRequestSchema(Schema):
    title: str | None = None


class ProjectDraftingContextRequestSchema(Schema):
    document_type: str | None = None
    locale: str = "it"
    task_id: int | None = None
    task_name: str | None = None
    activity_id: int | None = None
    activity_title: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    notes: str | None = None
    voice_original: str | None = None
    voice_italian: str | None = None
    draft_text: str | None = None
    evidence_excerpts: list[str] = []


class UpdateProjectAssistantSettingsRequestSchema(Schema):
    scope: str
    tone: str | None = None
    response_mode: str | None = None
    citation_mode: str | None = None
    custom_instructions: str | None = None
    preferred_model: str | None = None
    monthly_token_limit: int | None = None
    reset: bool = False


class ProjectDocumentWeatherSnapshotSchema(Schema):
    source: str | None = None
    recorded_at: str | None = None
    summary: str | None = None
    condition_type: str | None = None
    temperature_c: float | None = None
    feels_like_c: float | None = None
    humidity: float | None = None
    precipitation_probability: float | None = None
    precipitation_type: str | None = None
    wind_speed_kph: float | None = None
    wind_direction: str | None = None
    source_post_id: int | None = None


class ProjectDocumentEvidenceSchema(Schema):
    post_count: int = 0
    comment_count: int = 0
    media_count: int = 0
    document_count: int = 0
    photo_count: int = 0
    excerpts: list[str] = []
    weather_snapshots: list[ProjectDocumentWeatherSnapshotSchema] = []


class ProjectDocumentOperatorInputSchema(Schema):
    notes: str = ""
    voice_original: str | None = None
    voice_italian: str | None = None


class GenerateProjectDocumentDraftRequestSchema(Schema):
    document_type: str
    locale: str = "it"
    source_language: str | None = None
    task_id: int
    task_name: str
    activity_id: int | None = None
    activity_title: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    evidence: ProjectDocumentEvidenceSchema
    operator_input: ProjectDocumentOperatorInputSchema


class AutocompleteProjectDocumentDraftRequestSchema(Schema):
    document_type: str | None = None
    locale: str = "it"
    draft_text: str


class TranslateProjectDocumentTextRequestSchema(Schema):
    text: str
    source_language: str | None = None
    target_language: str | None = None


@router.get("/{project_id}/assistant", response=dict[str, Any], auth=auth)
def get_project_assistant_state_endpoint(request, project_id: int):
    try:
        thread_id_raw = request.GET.get("thread_id")
        thread_id = int(thread_id_raw) if thread_id_raw and thread_id_raw.isdigit() else None
        return get_project_assistant_state(
            profile=current_profile(request),
            project_id=project_id,
            thread_id=thread_id,
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post("/{project_id}/assistant/threads", response={201: dict[str, Any]}, auth=auth)
def create_project_assistant_thread_endpoint(
    request,
    project_id: int,
    payload: CreateAssistantThreadRequestSchema,
):
    try:
        response = create_assistant_thread_for_project(
            profile=current_profile(request),
            project_id=project_id,
            title=payload.title,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, response)


@router.patch("/{project_id}/assistant/settings", response=dict[str, Any], auth=auth)
def update_project_assistant_settings_endpoint(
    request,
    project_id: int,
    payload: UpdateProjectAssistantSettingsRequestSchema,
):
    try:
        return update_project_assistant_settings(
            profile=current_profile(request),
            project_id=project_id,
            scope=payload.scope,
            tone=payload.tone,
            response_mode=payload.response_mode,
            citation_mode=payload.citation_mode,
            custom_instructions=payload.custom_instructions,
            preferred_model=payload.preferred_model,
            monthly_token_limit=payload.monthly_token_limit,
            reset=payload.reset,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/{project_id}/assistant", response={201: dict[str, Any]}, auth=auth)
def ask_project_assistant_endpoint(
    request,
    project_id: int,
    payload: AskProjectAssistantRequestSchema,
):
    try:
        response = ask_project_assistant(
            profile=current_profile(request),
            project_id=project_id,
            message=payload.message,
            thread_id=payload.thread_id,
            force_sync=payload.force_sync,
            task_id=payload.task_id,
            activity_id=payload.activity_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, response)


@router.post("/{project_id}/assistant/stream", auth=auth)
def stream_project_assistant_endpoint(
    request,
    project_id: int,
    payload: AskProjectAssistantRequestSchema,
):
    try:
        prepared_run = prepare_project_assistant_run(
            profile=current_profile(request),
            project_id=project_id,
            message=payload.message,
            thread_id=payload.thread_id,
            force_sync=payload.force_sync,
            task_id=payload.task_id,
            activity_id=payload.activity_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc

    response = StreamingHttpResponse(
        iter_project_assistant_events(
            prepared_run=prepared_run,
            profile=current_profile(request),
            force_sync=payload.force_sync,
        ),
        content_type="text/event-stream; charset=utf-8",
    )
    response["Cache-Control"] = "no-cache, no-transform"
    response["Connection"] = "keep-alive"
    response["X-Accel-Buffering"] = "no"
    return response


@router.post("/{project_id}/assistant/drafting-context", response=dict[str, Any], auth=auth)
def get_project_drafting_context_endpoint(
    request,
    project_id: int,
    payload: ProjectDraftingContextRequestSchema,
):
    try:
        return get_project_drafting_context(
            profile=current_profile(request),
            project_id=project_id,
            document_type=payload.document_type,
            locale=payload.locale,
            task_id=payload.task_id,
            task_name=payload.task_name,
            activity_id=payload.activity_id,
            activity_title=payload.activity_title,
            date_from=payload.date_from,
            date_to=payload.date_to,
            notes=payload.notes,
            voice_original=payload.voice_original,
            voice_italian=payload.voice_italian,
            draft_text=payload.draft_text,
            evidence_excerpts=payload.evidence_excerpts,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/{project_id}/assistant/document-draft", response=dict[str, Any], auth=auth)
def generate_project_document_draft_endpoint(
    request,
    project_id: int,
    payload: GenerateProjectDocumentDraftRequestSchema,
):
    try:
        return generate_project_document_draft(
            profile=current_profile(request),
            project_id=project_id,
            document_type=payload.document_type,
            locale=payload.locale,
            source_language=payload.source_language,
            task_id=payload.task_id,
            task_name=payload.task_name,
            activity_id=payload.activity_id,
            activity_title=payload.activity_title,
            date_from=payload.date_from,
            date_to=payload.date_to,
            evidence=payload.evidence.dict(),
            operator_input=payload.operator_input.dict(),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/{project_id}/assistant/document-draft/autocomplete", response=dict[str, Any], auth=auth)
def autocomplete_project_document_draft_endpoint(
    request,
    project_id: int,
    payload: AutocompleteProjectDocumentDraftRequestSchema,
):
    try:
        return autocomplete_project_document_draft(
            profile=current_profile(request),
            project_id=project_id,
            document_type=payload.document_type,
            locale=payload.locale,
            draft_text=payload.draft_text,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/{project_id}/assistant/document-draft/translate", response=dict[str, Any], auth=auth)
def translate_project_document_text_endpoint(
    request,
    project_id: int,
    payload: TranslateProjectDocumentTextRequestSchema,
):
    try:
        return translate_project_document_text(
            profile=current_profile(request),
            project_id=project_id,
            text=payload.text,
            source_language=payload.source_language,
            target_language=payload.target_language,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
