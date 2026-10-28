"""Deterministic review of proposed labor rows; no AI, persistence or approval.

Names and supplied identity keys are declarations until the register's server
identity resolver authorizes them. A successful calculation is never consent.
"""
from datetime import date, datetime
import re
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA = "labor-proposal-v1"
DAY_MINUTES = 1500  # A local day may contain 25 hours at the autumn transition.


def _object(value, field):
    if not isinstance(value, dict):
        raise ValueError(f"{field}: oggetto richiesto.")
    return value


def _integer(value):
    return type(value) is int


def _text(value, field, maximum, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"{field}: testo non valido.")
    return value


def _instant(value, zone):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("Indica data, ora al minuto e offset esplicito.")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Indica data, ora al minuto e offset esplicito.") from exc
    local = instant.astimezone(zone)
    if local.replace(tzinfo=None) != instant.replace(tzinfo=None) or local.utcoffset() != instant.utcoffset():
        raise ValueError("L'offset non corrisponde al fuso e alla data dichiarati.")
    return instant


def labor_proposal(payload):
    payload = _object(payload, "payload")
    if payload.get("schema") != SCHEMA:
        raise ValueError("schema: versione della proposta non supportata.")
    project = payload.get("project_id")
    if not _integer(project) or project <= 0 or project > 2**63 - 1:
        raise ValueError("project_id: identificativo non valido.")
    day = payload.get("work_date")
    try:
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError()
        parsed_day = date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("work_date: data non valida.") from exc
    zone_name = _text(payload.get("timezone"), "timezone", 100)
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone: fuso IANA non valido.") from exc
    source = _object(payload.get("source"), "source")
    if source.get("kind") not in ("manual", "text", "transcript"):
        raise ValueError("source.kind: origine non supportata.")
    text = _text(source.get("text", ""), "source.text", 30000, empty=True)
    rows = payload.get("rows")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        raise ValueError("rows: indica da una a 200 righe.")
    ids, normalized = set(), []
    for index, raw in enumerate(rows):
        row = _object(raw, f"rows.{index}")
        try:
            row_id = str(UUID(row.get("id", "")))
            if row_id != row["id"].lower() or row_id in ids:
                raise ValueError()
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise ValueError(f"rows.{index}.id: UUID univoco richiesto.") from exc
        ids.add(row_id)
        issues = []

        def issue(field, code, message):
            issues.append({"field": field, "code": code, "message": message})

        subject = _object(row.get("subject"), f"rows.{index}.subject")
        kind = subject.get("kind")
        if kind not in ("person", "team"):
            raise ValueError(f"rows.{index}.subject.kind: tipo non supportato.")
        name = _text(subject.get("name"), f"rows.{index}.subject.name", 200, empty=True).strip()
        if not name:
            issue("subject.name", "name_required", "Indica la persona o la squadra.")
        identity = subject.get("key")
        if identity is not None:
            identity = _text(identity, f"rows.{index}.subject.key", 200)
        else:
            issue("subject.key", "identity_required", "Associa un'identità aziendale prima di registrare.")
        basis = subject.get("basis")
        if kind == "person" and basis != "per_person" or basis not in ("per_person", "person_total"):
            issue("subject.basis", "basis_required", "Specifica se la durata è per persona o un totale ore-persona.")
        count = subject.get("count")
        if kind == "person":
            if count != 1 or not _integer(count):
                issue("subject.count", "person_count", "Una riga nominativa rappresenta una persona.")
        elif count is not None and (not _integer(count) or not 1 <= count <= 500):
            issue("subject.count", "team_count", "Indica da una a 500 persone.")
        elif basis == "per_person" and count is None:
            issue("subject.count", "team_count_required", "Quante persone comprende la squadra dichiarata?")
        time = _object(row.get("time"), f"rows.{index}.time")
        mode, minutes = time.get("mode"), None
        if mode == "duration":
            amount = time.get("minutes")
            maximum = DAY_MINUTES * 500 if kind == "team" and basis == "person_total" else DAY_MINUTES
            if not _integer(amount) or not 0 < amount <= maximum:
                issue("time.minutes", "duration_required", "Indica una durata positiva in minuti, coerente con il periodo.")
            else:
                minutes = amount
        elif mode == "interval":
            if basis == "person_total":
                issue("time.mode", "interval_basis", "Un intervallo descrive la durata per persona, non un totale di squadra.")
            try:
                start, end = _instant(time.get("start"), zone), _instant(time.get("end"), zone)
                elapsed = int((end.timestamp() - start.timestamp()) // 60)
                if start.date() != parsed_day or not 0 < elapsed <= DAY_MINUTES:
                    raise ValueError("L'intervallo deve iniziare nel giorno indicato e avere durata valida.")
                pause = time.get("break_minutes")
                if not _integer(pause) or not 0 <= pause < elapsed:
                    issue("time.break_minutes", "break_required", "Indica la pausa effettiva, anche zero; deve essere inferiore all'intervallo.")
                else:
                    minutes = elapsed - pause
            except (ValueError, OverflowError) as exc:
                issue("time", "interval_invalid", str(exc))
        else:
            raise ValueError(f"rows.{index}.time.mode: modalità non supportata.")
        person_minutes = None
        quantity_valid = not any(i["field"].startswith("subject.") and i["field"] != "subject.name" and i["field"] != "subject.key" for i in issues)
        if minutes is not None and quantity_valid and not any(i["field"] == "time.mode" for i in issues):
            person_minutes = minutes if basis == "person_total" else minutes * count
            if kind == "team" and count is not None and person_minutes > DAY_MINUTES * count:
                issue("time.minutes", "team_duration_limit", "Il totale supera il tempo disponibile per il numero di persone dichiarato.")
                person_minutes = None
        span = row.get("source_span")
        if span is not None:
            span = _object(span, f"rows.{index}.source_span")
            first, last = span.get("start"), span.get("end")
            if not _integer(first) or not _integer(last) or not 0 <= first < last <= len(text):
                issue("source_span", "source_range", "Il riferimento non individua un passaggio valido della fonte.")
                span = None
            elif span.get("quote") != text[first:last]:
                issue("source_span", "source_quote", "La citazione non coincide con il testo sorgente.")
                span = None
            else:
                span = {"start": first, "end": last, "quote": text[first:last]}
        normalized.append({
            "id": row_id,
            "subject": {"kind": kind, "key": identity, "name": name, "basis": basis if basis in ("per_person", "person_total") else None, "count": count if _integer(count) and 1 <= count <= 500 else None},
            "time": {"mode": mode, "minutes": minutes} if mode == "duration" else {
                "mode": mode, "start": time.get("start") if isinstance(time.get("start"), str) else None,
                "end": time.get("end") if isinstance(time.get("end"), str) else None,
                "break_minutes": time.get("break_minutes") if _integer(time.get("break_minutes")) and 0 <= time["break_minutes"] <= DAY_MINUTES else None,
            },
            "source_span": span, "minutes": minutes, "person_minutes": person_minutes,
            "calculation_status": "needs_clarification" if issues else "complete",
            "identity_status": "unverified", "issues": issues,
            "overlap_check": "not_checked",
        })
    # Repeated rows for the same person may describe an accidental duplicate or
    # an intended split. Ask instead of silently counting both.
    by_identity = {}
    for row in normalized:
        key = row["subject"]["key"]
        if key:
            by_identity.setdefault(key, []).append(row)
    for group in by_identity.values():
        if len(group) > 1:
            for row in group:
                row["issues"].append({"field": "subject.key", "code": "repeated_identity", "message": "La stessa identità compare in più righe: verifica ripartizioni e duplicati."})
                row["calculation_status"] = "needs_clarification"
    return {
        "schema": SCHEMA, "project_id": project, "work_date": day, "timezone": zone_name,
        "source": {"kind": source["kind"], "text": text},
        "status": "proposal", "persistence": "not_saved", "requires_identity_validation": True,
        "rows": normalized,
        "totals": {
            "calculated_person_minutes": sum(r["person_minutes"] or 0 for r in normalized),
            "resolved_person_minutes": sum(r["person_minutes"] or 0 for r in normalized if not r["issues"]),
            "unresolved_rows": sum(bool(r["issues"]) for r in normalized),
        },
    }
