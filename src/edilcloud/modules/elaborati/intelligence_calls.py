"""Bounded specialist calls through the existing Responses adapter."""

from .checkpoints import run_step
from .content import digest
from .engine import BASE_INSTRUCTIONS
from .provider import strict_response_schema, structured_response

WORKFLOW_VERSION = "v3.2"


def specialist(*, job, key, stage, schema, data, instructions, effort="high", images=()):
    contract = {
        "data": data, "instructions": BASE_INSTRUCTIONS + "\n" + instructions + (
            "\nRestituisci un unico oggetto JSON valido e compatto, senza Markdown, preamboli o "
            "spaziature decorative. Completa soltanto l'incarico assegnato, con tutti i dettagli "
            "necessari e senza ripetizioni o riempitivi."
        ),
        "schema": strict_response_schema(schema, data.get("template"), data.get("evidence"), data),
        "effort": effort, "model": "gpt-6-luna", "output_policy": "provider_default",
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
