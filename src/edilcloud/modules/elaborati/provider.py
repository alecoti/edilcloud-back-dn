"""Small Responses API adapter; failures never masquerade as generated prose."""

import json

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import F
from pydantic import BaseModel

from .models import DocumentAIUsage, DocumentJob


class DocumentProviderError(Exception):
    pass


def structured_response(
    *,
    job,
    stage: str,
    schema: type[BaseModel],
    instructions: str,
    data: dict,
    effort="high",
    max_output_tokens=8192,
):
    if not settings.OPENAI_API_KEY:
        raise DocumentProviderError("Servizio di redazione AI non configurato.")
    body = {
        "model": "gpt-6-luna",
        "store": False,
        "reasoning": {"effort": effort},
        "max_output_tokens": max_output_tokens,
        "instructions": instructions,
        "input": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        "text": {
            "format": {
                "type": "json_schema",
                "name": stage,
                "strict": True,
                "schema": schema.model_json_schema(),
            }
        },
    }
    # Conservative UTF-8 upper bound, including schema and reasoning output.
    # A large source set must be narrowed rather than silently overdrawing quota.
    budget = len(json.dumps(body, ensure_ascii=False).encode()) + max_output_tokens
    job.refresh_from_db(fields=("consumed_tokens", "reserved_tokens"))
    remaining = job.reserved_tokens - job.consumed_tokens
    from .jobs import renew_lease

    renew_lease(job)
    try:
        # Do not automatically retry billable requests after ambiguous timeouts.
        with httpx.Client(timeout=httpx.Timeout(240, connect=15), follow_redirects=False) as client:
            if budget > remaining:
                # Count precisely before rejecting a source-rich weekly report.
                count = client.post(
                    f"{settings.OPENAI_API_BASE_URL.rstrip('/')}/responses/input_tokens",
                    json={
                        k: body[k] for k in ("model", "input", "instructions", "reasoning", "text")
                    },
                    headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                )
                if count.status_code >= 400:
                    raise DocumentProviderError(
                        "Impossibile verificare il budget delle fonti. Riprova o riduci il periodo."
                    )
                counted = count.json().get("input_tokens")
                if (
                    type(counted) is not int
                    or counted < 0
                    or counted + max_output_tokens > remaining
                ):
                    raise DocumentProviderError(
                        "Fonti troppo estese per il budget disponibile. Riduci il periodo o dividi l'elaborato."
                    )
            response = client.post(
                f"{settings.OPENAI_API_BASE_URL.rstrip('/')}/responses",
                json=body,
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        raise DocumentProviderError(
            "Il servizio AI non ha completato la richiesta. La bozza precedente resta disponibile."
        ) from exc
    if response.status_code >= 400:
        # Never expose provider bodies, API key configuration or private input.
        raise DocumentProviderError(
            f"Servizio AI temporaneamente non disponibile (HTTP {response.status_code})."
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise DocumentProviderError("Risposta AI non valida.") from exc
    usage = payload.get("usage") or {}
    response_id = payload.get("id")
    if not response_id:
        raise DocumentProviderError("Identificativo della risposta AI mancante.")
    # Record consumed tokens even for an incomplete response, a refusal, or a
    # later schema/quality failure. The billing summary includes these records.
    with transaction.atomic():
        record, created = DocumentAIUsage.objects.get_or_create(
            response_id=response_id,
            defaults={
                "job": job,
                "workspace_id": job.revision.elaborato.project.workspace_id,
                "stage": stage,
                "input_tokens": max(0, int(usage.get("input_tokens", 0))),
                "output_tokens": max(0, int(usage.get("output_tokens", 0))),
                "total_tokens": max(0, int(usage.get("total_tokens", 0))),
            },
        )
        if created:
            DocumentJob.objects.filter(pk=job.pk).update(
                consumed_tokens=F("consumed_tokens") + record.total_tokens
            )
            from edilcloud.modules.billing.services import apply_ai_usage_to_billing

            apply_ai_usage_to_billing(
                workspace=job.revision.elaborato.project.workspace,
                total_tokens=record.total_tokens,
                reference_id=f"elaborati:{record.pk}",
            )
    renew_lease(job)
    if payload.get("status") != "completed":
        raise DocumentProviderError(
            "La redazione AI si è interrotta prima del completamento. Nessun testo incompleto è stato applicato."
        )
    texts = [
        part.get("text", "")
        for item in payload.get("output", [])
        if item.get("type") == "message"
        for part in item.get("content", [])
        if part.get("type") == "output_text"
    ]
    try:
        return schema.model_validate_json("".join(texts))
    except ValueError as exc:
        raise DocumentProviderError(
            "La risposta AI non rispetta lo schema dell'elaborato."
        ) from exc
