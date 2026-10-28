"""Validate source-backed AI suggestions; no network, identity or approval effects."""
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID
from .labor_proposals import labor_proposal

CONTRACT = json.loads(Path(__file__).with_name("labor_interpretation_v1.json").read_text(encoding="utf-8"))


def request_input(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload: oggetto richiesto.")
    command = payload.get("command_id")
    try:
        if not isinstance(command, str) or str(UUID(command)) != command.lower():
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("command_id: UUID non valido.") from exc
    source = payload.get("source")
    if not isinstance(source, dict) or source.get("kind") not in ("text", "transcript"):
        raise ValueError("source.kind: indica testo o trascrizione.")
    text = source.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 30000:
        raise ValueError("source.text: indica da uno a 30.000 caratteri.")
    value = {"schema": "labor-proposal-v1", "project_id": payload.get("project_id"),
             "work_date": payload.get("work_date"), "timezone": payload.get("timezone"),
             "source": {"kind": source["kind"], "text": text}, "rows": [{
                 "id": command.lower(), "subject": {"kind": "person", "key": None, "name": "", "basis": "per_person", "count": 1},
                 "time": {"mode": "duration", "minutes": None}}]}
    labor_proposal(value)  # Validates context, without inventing a row or saving it.
    value.pop("rows")
    value["command_id"] = command.lower()
    return value


def provider_body(request):
    return {"model": "gpt-6-luna", "store": False, "stream": False,
            "reasoning": {"effort": "low"}, "max_output_tokens": 16000,
            "instructions": CONTRACT["instructions"],
            "input": json.dumps({k: request[k] for k in ("work_date", "timezone", "source")}, ensure_ascii=False, separators=(",", ":")),
            "text": {"format": {"type": "json_schema", "name": "labor_interpretation_v1", "strict": True, "schema": CONTRACT["output_schema"]}}}


def _integer(value, minimum, maximum, *, nullable=False):
    if nullable and value is None:
        return value
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("La proposta AI contiene una quantità non valida.")
    return value


def _text(value, maximum, *, nullable=False):
    if nullable and value is None:
        return value
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError("La proposta AI contiene un testo non valido.")
    return value


def row_id(command, index):
    raw = bytearray(sha256(f"edilcloud:labor-ai-row-v1:{command}:{index}".encode()).digest()[:16])
    raw[6], raw[8] = (raw[6] & 15) | 128, (raw[8] & 63) | 128
    return str(UUID(bytes=bytes(raw)))


def normalize(request, result):
    """A matching quote proves traceability, never factual or semantic truth."""
    if not isinstance(result, dict) or set(result) != {"rows", "notes"}:
        raise ValueError("La proposta AI non rispetta il contratto previsto.")
    rows, notes = result["rows"], result["notes"]
    if not isinstance(rows, list) or len(rows) > 64 or not isinstance(notes, list) or len(notes) > 20:
        raise ValueError("La proposta AI supera il limite di righe o chiarimenti.")
    notes = [_text(note, 1000) for note in notes]
    text, normalized = request["source"]["text"], []
    required = set(CONTRACT["output_schema"]["properties"]["rows"]["items"]["properties"])
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("Una riga AI non rispetta il contratto previsto.")
        if row["kind"] not in ("person", "team") or row["basis"] not in (None, "per_person", "person_total") or row["time_mode"] not in ("duration", "interval", "unknown"):
            raise ValueError("La proposta AI contiene una modalità non valida.")
        name = _text(row["name"], 200)
        count = _integer(row["count"], 1, 500, nullable=True)
        hours = _integer(row["duration_hours"], 0, 12500, nullable=True)
        minutes = _integer(row["duration_minutes"], 0, 750000, nullable=True)
        pause = _integer(row["break_minutes"], 0, 1500, nullable=True)
        start = _text(row["start"], 40, nullable=True)
        end = _text(row["end"], 40, nullable=True)
        quote = _text(row["quote"], 4000)
        occurrence = _integer(row["quote_occurrence"], 0, 30000)
        first = -1
        for _ in range(occurrence + 1):
            first = text.find(quote, first + 1) if quote else -1
            if first < 0:
                raise ValueError("Una citazione AI non coincide con la fonte. Il testo originale è conservato.")
        if row["time_mode"] == "interval":
            time = {"mode": "interval", "start": start, "end": end, "break_minutes": pause}
        else:
            amount = (hours or 0) * 60 + (minutes or 0) if hours is not None or minutes is not None else None
            time = {"mode": "duration", "minutes": amount if row["time_mode"] == "duration" else None}
        normalized.append({"id": row_id(request["command_id"], index),
            "subject": {"kind": row["kind"], "key": None, "name": name, "basis": row["basis"], "count": count},
            "time": time, "source_span": {"start": first, "end": first + len(quote), "quote": quote}})
    proposal_input = {k: request[k] for k in ("schema", "project_id", "work_date", "timezone", "source")}
    proposal_input["rows"] = normalized
    return {"input": proposal_input if normalized else None,
            "proposal": labor_proposal(proposal_input) if normalized else None,
            "notes": notes, "requires_human_review": True, "registered_minutes": 0}
