import pytest
from django.test import override_settings

from edilcloud.openai_models import resolve_text_model, resolve_transcription_model, responses_generation_options
from edilcloud.modules.assistant.services import build_openai_responses_payload
from edilcloud.modules.assistant.document_drafting import document_draft_model
from edilcloud.modules.projects.services import project_content_translation_model, extract_openai_output_text


@pytest.mark.parametrize("legacy", [None, "", "gpt-4o-mini", " gpt-4o-mini ", "gpt-4o-mini-2024-07-18"])
def test_old_text_configuration_routes_to_luna(legacy):
    assert resolve_text_model(legacy) == "gpt-6-luna"


def test_other_workloads_and_explicit_model_choices_are_preserved():
    assert resolve_text_model("gpt-4.1") == "gpt-4.1"
    assert resolve_transcription_model("gpt-4o-mini-transcribe") == "gpt-4o-transcribe"
    assert resolve_transcription_model("whisper-1") == "whisper-1"


@override_settings(AI_ASSISTANT_MODEL="gpt-4o-mini", AI_ASSISTANT_REASONING_EFFORT="low")
def test_chat_stream_uses_reasoning_without_unsupported_sampling_or_storage():
    payload = build_openai_responses_payload(system_prompt="Rispondi dai fatti", user_prompt="Quali sono i vincoli?", stream=True)
    assert payload["model"] == "gpt-6-luna"
    assert payload["reasoning"] == {"effort": "low"}
    assert "temperature" not in payload
    assert payload["store"] is False
    assert payload["stream"] is True


@override_settings(AI_DRAFT_MODEL="gpt-4o-mini", PROJECT_CONTENT_TRANSLATION_MODEL="gpt-4o-mini")
def test_drafts_and_translation_overrides_cannot_keep_calling_old_mini():
    assert document_draft_model() == project_content_translation_model() == "gpt-6-luna"
    assert responses_generation_options(model=project_content_translation_model(), temperature=0.1, reasoning_effort="none") == {"reasoning": {"effort": "none"}, "temperature": 0.1}


def test_reasoning_items_are_not_exposed_as_user_text():
    assert extract_openai_output_text({"output": [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Private planning"}]},
        {"type": "message", "content": [{"type": "output_text", "text": "La dipendenza richiede di attendere."}]},
    ]}) == "La dipendenza richiede di attendere."
