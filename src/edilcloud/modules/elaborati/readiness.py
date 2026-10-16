"""Deterministic documentary coverage; a catalogue is not evidence of a day."""

from collections import Counter
from datetime import date
import re


def coverage_summary(bundle):
    sources = bundle.get("sources", [])
    counts = Counter(s["kind"] for s in sources)
    start, end = bundle.get("period_start", ""), bundle.get("period_end", "")
    dated_documents = []
    for source in sources:
        if source["kind"] != "document":
            continue
        # Only explicit dates in extracted content, not upload/index timestamps.
        text = "\n".join(e.get("text", "") for e in source["data"].get("excerpts", []))
        for value in re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{2}/\d{2}/\d{4}\b", text):
            try:
                candidate = (
                    date.fromisoformat(value)
                    if "-" in value
                    else date(*map(int, value.split("/")[::-1]))
                )
            except ValueError:
                continue
            if start <= candidate.isoformat() <= end:
                dated_documents.append(source["id"])
                break
    operational = sum(
        s["kind"] in {"post", "comment", "event", "declaration"}
        and not s["data"].get("outside_period_context", False)
        for s in sources
    )
    return {
        "counts_by_kind": dict(counts),
        "operational_sources_in_period": operational,
        "documents_mentioning_period_dates": dated_documents,
        "photographs": counts["photo"] + counts["image_attachment"],
        "documents_without_excerpts": [
            s["id"] for s in sources if s["kind"] == "document" and not s["data"].get("excerpts")
        ],
        "audio_without_transcript": [
            s["id"]
            for s in sources
            if s["data"].get("media_kind") == "audio" and not s["data"].get("transcript")
        ],
        "selection_is_partial": bool(bundle.get("truncated")),
    }


def require_documentary_material(bundle, document_type):
    summary = coverage_summary(bundle)
    if document_type == "photo_report" and not summary["photographs"]:
        raise ValueError(
            "Nel periodo selezionato non ci sono fotografie utilizzabili. Scegli un periodo con immagini o aggiungi le fotografie prima di creare una relazione fotografica."
        )
    if (
        not summary["operational_sources_in_period"]
        and not summary["documents_mentioning_period_dates"]
        and not summary["photographs"]
    ):
        nearby = bundle.get("nearby_post_dates", [])
        hint = " Date vicine con post: " + ", ".join(nearby) + "." if nearby else ""
        raise ValueError(
            "Non risultano registrazioni operative per il periodo selezionato. Le anagrafiche e le date di progetto non documentano quella giornata. Verifica cantiere e periodo o inserisci una dichiarazione."
            + hint
        )
    return summary


def documentary_issues(editor, bundle, document_type):
    from .content import editor_claims

    issues = []

    def issue(message, severity="blocking"):
        issues.append({"section_key": "", "text": "", "severity": severity, "explanation": message})

    if document_type == "photo_report" and not any(
        n["type"] == "evidencePhoto" for n in editor.get("content", [])
    ):
        issue(
            "Una relazione fotografica deve contenere fotografie effettive, non soltanto descrizioni o nomi di file."
        )
    claims = editor_claims(editor)
    substantive = [
        c for c in claims if c["nature"] != "unverified" and c["section_key"] != "photographs"
    ]
    operational_kinds = {
        "post",
        "comment",
        "document",
        "declaration",
        "event",
        "photo",
        "image_attachment",
        "drawing_pin",
    }
    operational_ids = {s["id"] for s in bundle.get("sources", []) if s["kind"] in operational_kinds}
    if claims and not any(set(c["source_ids"]) & operational_ids for c in substantive):
        issue(
            "Il documento non utilizza evidenze operative: anagrafiche e richiesta non bastano a descrivere il lavoro svolto."
        )
    for claim in claims:
        if re.search(r"\bunverified\b", claim["text"], re.IGNORECASE):
            issues.append(
                {
                    "section_key": claim["section_key"],
                    "text": claim["text"],
                    "severity": "blocking",
                    "explanation": "Usare una dicitura comprensibile nella lingua del documento, senza etichette tecniche interne.",
                }
            )
    return issues
