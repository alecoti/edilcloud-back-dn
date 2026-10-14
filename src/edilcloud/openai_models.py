"""Model aliases and Responses parameters for the GPT-6 Luna migration."""

from __future__ import annotations

import re


DEFAULT_TEXT_MODEL = "gpt-6-luna"
DEFAULT_TRANSCRIPTION_MODEL = "gpt-4o-transcribe"


def resolve_text_model(value: str | None) -> str:
    model = (value or "").strip()
    if not model or model == "gpt-4o-mini" or re.fullmatch(r"gpt-4o-mini-\d{4}-\d{2}-\d{2}", model):
        return DEFAULT_TEXT_MODEL
    return model


def resolve_transcription_model(value: str | None) -> str:
    model = (value or "").strip()
    # Luna accepts text/images, not audio. ASR remains a dedicated first step.
    return DEFAULT_TRANSCRIPTION_MODEL if not model or model == "gpt-4o-mini-transcribe" else model


def responses_generation_options(*, model: str, temperature: float, reasoning_effort: str = "low") -> dict:
    if resolve_text_model(model).startswith("gpt-6-luna"):
        effort = (reasoning_effort or "low").strip().lower()
        if effort not in {"none", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Livello di ragionamento OpenAI non valido.")
        # Temperature is incompatible with enabled reasoning. Explicit none keeps
        # translations quick and deterministic at the caller's existing sampling level.
        return {"reasoning": {"effort": effort}, **({"temperature": temperature} if effort == "none" else {})}
    return {"temperature": temperature}
