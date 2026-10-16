"""Small Responses API adapter; failures never masquerade as generated prose."""

import json
import time
from copy import deepcopy
from contextlib import contextmanager
from threading import Event, Thread

import httpx
from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import F
from pydantic import BaseModel, ValidationError

from .models import DocumentAIUsage, DocumentJob, DocumentAudit

# Full model allowance, shared by analysis, composition, review and editor actions.
# Includes reasoning tokens; it is a ceiling, never a requested document length.
LUNA_MAX_OUTPUT_TOKENS = 128_000


class DocumentProviderError(Exception):
    pass


@contextmanager
def provider_heartbeat(job):
    """Long reasoning calls keep the existing fenced worker lease alive."""
    from .jobs import renew_lease
    from .checkpoints import CURRENT_STEP, renew_current_step, step_context

    stop = Event()
    active_step = CURRENT_STEP.get()

    def heartbeat():
        close_old_connections()
        try:
            while not stop.wait(45):
                try:
                    renew_lease(job)
                    with step_context(active_step):
                        renew_current_step()
                except RuntimeError:
                    # Never reacquire another worker's lease. The response path
                    # still records usage before its final ownership check.
                    break
        finally:
            close_old_connections()

    thread = Thread(target=heartbeat, daemon=True, name="elaborati-provider-lease")
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)


def strict_response_schema(model, template=None, evidence=None):
    """Responses requires every object property, including defaulted list fields."""
    schema = model.model_json_schema()

    def walk(value):
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema)
    if template and model.__name__ == "Composition":
        # Object keys, unlike an array plus prose instructions, require every
        # frozen section exactly once. The application supplies their order.
        section = schema["$defs"]["Section"]
        section["properties"].pop("key")
        section["required"].remove("key")
        keys = [s["key"] for s in template["sections"]]
        schema["properties"]["sections"] = {
            "type": "object",
            "properties": {key: {"$ref": "#/$defs/Section"} for key in keys},
            "required": keys,
            "additionalProperties": False,
        }
        from .document_structure import registers_for

        for key, registers in registers_for(template).items():
            if key not in keys:
                continue
            specific = deepcopy(section)
            required_tables = {}
            for register in registers:
                required_tables[register["key"]] = {
                    "type": "object",
                    "properties": {
                        "rows": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "properties": {
                                    column: {"$ref": "#/$defs/ClaimCell"}
                                    for column in register["columns"]
                                },
                                "required": register["columns"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["rows"],
                    "additionalProperties": False,
                }
            specific["properties"]["required_tables"] = {
                "type": "object",
                "properties": required_tables,
                "required": list(required_tables),
                "additionalProperties": False,
            }
            specific["required"].append("required_tables")
            schema["properties"]["sections"]["properties"][key] = specific
        # Inline fields are actual structured values on the wire. The model
        # must not coordinate a hand-written {{token}} with a separate list;
        # that redundant representation caused expensive valid drafts to fail.
        claim = schema["$defs"]["Claim"]
        caption = deepcopy(claim)
        caption["properties"]["fields"]["maxItems"] = 0
        schema["$defs"]["PhotoCaption"] = caption
        schema["$defs"]["Photograph"]["properties"]["caption"] = {"$ref": "#/$defs/PhotoCaption"}
        claim["properties"].pop("text")
        claim["properties"].pop("fields")
        claim["required"] = ["source_ids", "nature", "parts"]
        claim["properties"]["parts"] = {
            "type": "array",
            "minItems": 1,
            "items": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                        "additionalProperties": False,
                    },
                    {
                        "type": "object",
                        "properties": {"field": {"$ref": "#/$defs/EditableField"}},
                        "required": ["field"],
                        "additionalProperties": False,
                    },
                ]
            },
        }
        # Match supplementary columns and rows in the provider schema too.
        table = schema["$defs"]["ClaimTable"]
        variants = []
        for count in range(2, 7):
            variant = deepcopy(table)
            properties = variant["properties"]
            properties["columns"].update(minItems=count, maxItems=count)
            properties["rows"]["items"].update(minItems=count, maxItems=count)
            properties["rows"]["items"]["items"] = {"$ref": "#/$defs/ClaimCell"}
            properties["widths"] = {
                "anyOf": [
                    {"type": "array", "items": {"type": "integer"}, "maxItems": 0},
                    {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1, "maximum": 100},
                        "minItems": count,
                        "maxItems": count,
                    },
                ]
            }
            variants.append(variant)
        schema["$defs"]["ClaimTable"] = {"anyOf": variants}
    if evidence and evidence.get("sources"):
        definitions = schema.setdefault("$defs", {})
        definitions["EvidenceSourceId"] = {
            "type": "string",
            "enum": [s["id"] for s in evidence["sources"]],
        }
        for definition in list(definitions.values()):
            source_ids = definition.get("properties", {}).get("source_ids")
            if source_ids:
                source_ids["items"] = {"$ref": "#/$defs/EvidenceSourceId"}
        if "Photograph" in definitions:
            photo_ids = [
                s["id"] for s in evidence["sources"] if s["kind"] in {"photo", "image_attachment"}
            ]
            definitions["Photograph"]["properties"]["source_id"] = {
                "type": "string",
                "enum": photo_ids or ["__no_photographs_available__"],
            }
            if not photo_ids:
                schema["properties"]["photographs"]["maxItems"] = 0
    return schema


def decode_document_parts(value, *, existing_field_ids=()):
    """Build editor marker strings ourselves; no factual text is rewritten."""
    seen = set()
    protected = set(existing_field_ids)

    def decode(item):
        if isinstance(item, list):
            for child in item:
                decode(child)
        elif isinstance(item, dict):
            if "parts" in item and "source_ids" in item and "nature" in item:
                text_parts = []
                fields = []
                for part in item.pop("parts"):
                    if "text" in part:
                        text_parts.append(part["text"])
                    else:
                        field = deepcopy(part["field"])
                        key = field["key"]
                        if key in seen:
                            if key in protected:
                                raise ValueError("Campo esistente duplicato nella proposta.")
                            suffix = 2
                            while f"{key[:90]}.{suffix}" in seen:
                                suffix += 1
                            field["key"] = f"{key[:90]}.{suffix}"
                        seen.add(field["key"])
                        fields.append(field)
                        text_parts.append("{{" + field["key"] + "}}")
                item["text"] = "".join(text_parts)
                item["fields"] = fields
            for child in item.values():
                decode(child)

    decode(value)
    return value


def structured_response(
    *,
    job,
    stage: str,
    schema: type[BaseModel],
    instructions: str,
    data: dict,
    effort="high",
    max_output_tokens=LUNA_MAX_OUTPUT_TOKENS,
    images=(),
):
    from .checkpoints import ProviderCheckpoint

    checkpoint = ProviderCheckpoint(job, stage=stage, model="gpt-6-luna", effort=effort)
    cached_payload = checkpoint.restore()
    if not settings.OPENAI_API_KEY and cached_payload is None:
        raise DocumentProviderError("Servizio di redazione AI non configurato.")
    body = {
        "model": "gpt-6-luna",
        "store": False,
        "stream": True,
        "reasoning": {"effort": effort},
        "max_output_tokens": max_output_tokens,
        "instructions": instructions,
        "input": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        "text": {
            "format": {
                "type": "json_schema",
                "name": stage,
                "strict": True,
                "schema": strict_response_schema(
                    schema, data.get("template"), data.get("evidence")
                ),
            }
        },
    }
    if effort != "none":
        body["reasoning"]["summary"] = "auto"
    if images:
        if len(images) > 12:
            raise ValueError("Troppe immagini per una singola analisi documentale.")
        body["input"] = [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": body["input"]},
                    *[
                        part
                        for source_id, uri in images
                        for part in (
                            {"type": "input_text", "text": f"Image source: {source_id}"},
                            {"type": "input_image", "image_url": uri, "detail": "high"},
                        )
                    ],
                ],
            }
        ]
    # Conservative UTF-8 upper bound, including schema and reasoning output.
    # A large source set must be narrowed rather than silently overdrawing quota.
    budget = len(json.dumps(body, ensure_ascii=False).encode()) + max_output_tokens
    job.refresh_from_db(fields=("consumed_tokens", "reserved_tokens"))
    remaining = job.reserved_tokens - job.consumed_tokens
    from edilcloud.modules.billing.services import (
        ai_quota_is_unlimited,
        get_workspace_billing_account,
    )

    unlimited = ai_quota_is_unlimited(
        get_workspace_billing_account(job.revision.elaborato.project.workspace)
    )
    from .jobs import renew_lease

    renew_lease(job)
    started = time.monotonic()
    response_id = None
    progress = None
    payload = cached_payload

    def created(identifier):
        nonlocal response_id
        response_id = identifier
        checkpoint.created(identifier)
        DocumentAudit.objects.create(
            revision=job.revision,
            actor=job.requested_by,
            action="ai.started",
            detail={
                "stage": stage,
                "response_id": identifier,
                "output_limit": max_output_tokens,
                "reasoning_effort": effort,
                "transport": "stream",
            },
        )

    try:
        # Do not automatically retry billable requests after ambiguous timeouts.
        if payload is None:
            with (
                provider_heartbeat(job),
                httpx.Client(timeout=httpx.Timeout(1800, connect=15), follow_redirects=False) as client,
            ):
                if (checkpoint.step or budget > remaining) and not unlimited:
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
                        or (not checkpoint.step and counted + max_output_tokens > remaining)
                    ):
                        raise DocumentProviderError(
                            "Fonti troppo estese per il budget disponibile. Riduci il periodo o dividi l'elaborato."
                        )
                    budget = counted + max_output_tokens
                from .provider_stream import read_response
                from .thinking import ReasoningProgress

                progress = ReasoningProgress(job, stage)
                for attempt in range(2):
                    checkpoint.sent(reservation=budget)
                    with client.stream(
                        "POST",
                        f"{settings.OPENAI_API_BASE_URL.rstrip('/')}/responses",
                        json=body,
                        headers={
                            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                            "Content-Type": "application/json",
                        },
                    ) as response:
                        if response.status_code >= 400:
                            # Only an explicit rejection before generation can
                            # safely fall back from the optional summary flag.
                            response.read()
                            try:
                                error = response.json().get("error") or {}
                            except (ValueError, AttributeError):
                                error = {}
                            if not isinstance(error, dict):
                                error = {}
                            if response.status_code in {400, 401, 403, 404, 413, 422, 429}:
                                checkpoint.rejected(f"HTTP_{response.status_code}")
                            if (
                                attempt == 0
                                and response.status_code in {400, 403}
                                and error.get("param") == "reasoning.summary"
                                and "summary" in body["reasoning"]
                            ):
                                body["reasoning"].pop("summary")
                                continue
                            raise DocumentProviderError(
                                f"Servizio AI temporaneamente non disponibile (HTTP {response.status_code})."
                            )
                        payload = read_response(
                            response, on_created=created, on_summary=progress.summary
                        )
                        checkpoint.completed(payload)
                        break
    except (httpx.HTTPError, ValueError) as exc:
        if response_id:
            DocumentAudit.objects.create(
                revision=job.revision,
                actor=job.requested_by,
                action="ai.stream_interrupted",
                detail={"stage": stage, "response_id": response_id, "usage_unknown": True},
            )
        raise DocumentProviderError(
            "Il servizio AI non ha completato la richiesta. La bozza precedente resta disponibile."
        ) from exc
    finally:
        if payload is None:
            checkpoint.interrupted()
        if progress:
            progress.finish(payload.get("status") if payload else "interrupted")
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
                "attempt": checkpoint.attempt,
                "input_tokens": max(0, int(usage.get("input_tokens", 0))),
                "output_tokens": max(0, int(usage.get("output_tokens", 0))),
                "total_tokens": max(0, int(usage.get("total_tokens", 0))),
            },
        )
        if checkpoint.attempt:
            from .models import DocumentStepAttempt

            DocumentStepAttempt.objects.filter(pk=checkpoint.attempt.pk).update(reserved_tokens=0)
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
            DocumentAudit.objects.create(
                revision=job.revision,
                actor=job.requested_by,
                action="ai.response",
                detail={
                    "stage": stage,
                    "model": body["model"],
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "reasoning_tokens": (usage.get("output_tokens_details") or {}).get(
                        "reasoning_tokens", 0
                    ),
                    "cached_input_tokens": (usage.get("input_tokens_details") or {}).get(
                        "cached_tokens", 0
                    ),
                    "output_limit": max_output_tokens,
                    "reasoning_effort": effort,
                    "status": payload.get("status"),
                    "duration_ms": round((time.monotonic() - started) * 1000),
                },
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
        value = json.loads("".join(texts))
        if schema.__name__ == "Composition" and isinstance(value.get("sections"), dict):
            value["sections"] = [
                {**value["sections"][section["key"]], "key": section["key"]}
                for section in data["template"]["sections"]
            ]
            from .fields import fields_in

            decode_document_parts(
                value, existing_field_ids=[f["fieldId"] for f in fields_in(job.revision.editor_doc)]
            )
            from .document_structure import decode_registers

            decode_registers(value, data["template"])
        return schema.model_validate(value)
    except (ValueError, KeyError, TypeError) as exc:
        # Explain structural failures without storing provider text, hidden
        # reasoning, source content or credential details in diagnostic events.
        locations = (
            [
                {"location": list(error["loc"]), "type": error["type"]}
                for error in exc.errors(include_input=False, include_context=False)[:30]
            ]
            if isinstance(exc, ValidationError)
            else [{"type": type(exc).__name__}]
        )
        DocumentAudit.objects.create(
            revision=job.revision,
            actor=job.requested_by,
            action="ai.schema_invalid",
            detail={"stage": stage, "errors": locations},
        )
        raise DocumentProviderError(
            "La risposta AI non rispetta lo schema dell'elaborato."
        ) from exc
