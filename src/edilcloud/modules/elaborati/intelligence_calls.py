"""Bounded specialist calls through the existing Responses adapter."""

from .checkpoints import run_step
from .content import digest
from .engine import BASE_INSTRUCTIONS
from .provider import LUNA_MAX_OUTPUT_TOKENS, strict_response_schema, structured_response

WORKFLOW_VERSION = "v3.1"


def specialist(*, job, key, stage, schema, data, instructions, effort="high", images=()):
    contract = {
        "data": data, "instructions": BASE_INSTRUCTIONS + "\n" + instructions,
        "schema": strict_response_schema(schema, data.get("template"), data.get("evidence")),
        "effort": effort, "model": "gpt-6-luna", "max_output_tokens": LUNA_MAX_OUTPUT_TOKENS,
        "images": [(sid, digest(uri)) for sid, uri in images],
    }
    return run_step(
        job=job, key=key, kind=stage, data=contract, schema=schema,
        contract_version=WORKFLOW_VERSION,
        execute=lambda step: structured_response(
            job=job, stage=stage, schema=schema, data=data,
            instructions=contract["instructions"], effort=effort, images=images,
        ),
    )
