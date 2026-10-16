"""Read Responses SSE results; allow only explicitly public reasoning summaries.

Only a terminal response can enter document validation or billing. Deltas are
discarded from document output; an interrupted request is never replayed.
"""

import json


def read_response(response, *, on_created=None, on_summary=None):
    def summary(output_index, summary_index, text, *, append=False, complete=True):
        if (
            on_summary
            and type(output_index) is int
            and type(summary_index) is int
            and output_index >= 0
            and summary_index >= 0
            and isinstance(text, str)
        ):
            on_summary(output_index, summary_index, text, append=append, complete=complete)

    def item_summaries(item, output_index):
        if isinstance(item, dict) and item.get("type") == "reasoning":
            for index, part in enumerate(item.get("summary") or []):
                if isinstance(part, dict) and part.get("type") == "summary_text":
                    summary(output_index, index, part.get("text"))

    def final_summaries(payload):
        if on_summary:
            for index, item in enumerate(payload.get("output") or []):
                item_summaries(item, index)

    # Some compatible gateways return one final JSON response despite stream.
    if "text/event-stream" not in response.headers.get("content-type", ""):
        response.read()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Risposta AI non valida.")
        final_summaries(payload)
        return payload
    data = []
    size = 0

    def event(lines):
        if not lines:
            return None
        raw = "\n".join(lines)
        if raw == "[DONE]":
            return None
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Evento AI non valido.")
        kind = value.get("type")
        if kind == "response.reasoning_summary_text.delta":
            summary(
                value.get("output_index"),
                value.get("summary_index"),
                value.get("delta"),
                append=True,
                complete=False,
            )
        elif kind == "response.reasoning_summary_text.done":
            summary(value.get("output_index"), value.get("summary_index"), value.get("text"))
        elif kind == "response.reasoning_summary_part.done":
            part = value.get("part") or {}
            if isinstance(part, dict) and part.get("type") == "summary_text":
                summary(value.get("output_index"), value.get("summary_index"), part.get("text"))
        elif kind == "response.output_item.done":
            item_summaries(value.get("item"), value.get("output_index"))
        if kind == "response.created" and on_created:
            identifier = (value.get("response") or {}).get("id")
            if isinstance(identifier, str):
                on_created(identifier)
        if kind in {"response.completed", "response.incomplete", "response.failed"}:
            result = value.get("response")
            if not isinstance(result, dict):
                raise ValueError("Evento finale AI non valido.")
            final_summaries(result)
            return result
        if kind == "error":
            # Provider error text can contain input or configuration details.
            raise ValueError("Il servizio AI ha interrotto la risposta.")
        return None

    for line in response.iter_lines():
        if not line:
            result = event(data)
            if result is not None:
                return result
            data = []
            size = 0
        elif line.startswith("data:"):
            fragment = line[5:].lstrip(" ")
            size += len(fragment)
            if size > 8_000_000:
                raise ValueError("Evento AI non valido.")
            data.append(fragment)
    result = event(data)
    if result is not None:
        return result
    raise ValueError("Risposta AI interrotta prima dell'evento finale.")
