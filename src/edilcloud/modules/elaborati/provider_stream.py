"""Read complete Responses SSE results without exposing or saving reasoning.

Only a terminal response can enter document validation or billing. Deltas are
discarded; an interrupted request is never automatically replayed.
"""

import json


def read_response(response, *, on_created=None):
    # Some compatible gateways return one final JSON response despite stream.
    if "text/event-stream" not in response.headers.get("content-type", ""):
        response.read()
        return response.json()
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
        if kind == "response.created" and on_created:
            identifier = (value.get("response") or {}).get("id")
            if isinstance(identifier, str):
                on_created(identifier)
        if kind in {"response.completed", "response.incomplete", "response.failed"}:
            result = value.get("response")
            if not isinstance(result, dict):
                raise ValueError("Evento finale AI non valido.")
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
