"""One bounded, portable Tiptap schema for web, native editor and PDF."""

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    source_ids: list[str] = Field(max_length=40)
    nature: str = Field(pattern="^(observed|reported|proposed|decided|unverified)$")


class Finding(Claim):
    key: str = Field(max_length=64)


class ReasoningResult(StrictModel):
    facts: list[Finding] = Field(max_length=240)
    duplicates: list[str] = Field(max_length=100)
    contradictions: list[str] = Field(max_length=80)
    missing_data: list[str] = Field(max_length=80)


class Section(StrictModel):
    key: str = Field(max_length=64)
    paragraphs: list[Claim] = Field(max_length=60)


class Photograph(StrictModel):
    source_id: str
    caption: Claim


class Composition(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    sections: list[Section] = Field(max_length=20)
    photographs: list[Photograph] = Field(max_length=24)


class QualityIssue(StrictModel):
    section_key: str
    text: str
    severity: str = Field(pattern="^(warning|blocking)$")
    explanation: str


class QualityResult(StrictModel):
    issues: list[QualityIssue] = Field(max_length=120)
    missing_data: list[str] = Field(max_length=80)


def editor_from_composition(composition: Composition, template: dict) -> dict:
    expected = [s["key"] for s in template["sections"]]
    if [s.key for s in composition.sections] != expected:
        raise ValueError("Le sezioni generate non rispettano il template.")
    content = []
    for definition, section in zip(template["sections"], composition.sections, strict=True):
        content.append(
            {
                "type": "heading",
                "attrs": {"level": 2, "sectionKey": section.key},
                "content": [{"type": "text", "text": definition["label"]}],
            }
        )
        for claim in section.paragraphs:
            content.append(
                {
                    "type": "paragraph",
                    "attrs": {
                        "sectionKey": section.key,
                        "sourceIds": claim.source_ids,
                        "nature": claim.nature,
                    },
                    "content": [{"type": "text", "text": claim.text}],
                }
            )
    for photo in composition.photographs:
        content.append(
            {
                "type": "evidencePhoto",
                "attrs": {
                    "sourceId": photo.source_id,
                    "caption": photo.caption.text,
                    "sourceIds": photo.caption.source_ids,
                    "nature": photo.caption.nature,
                },
            }
        )
    return {"type": "doc", "content": content}


def validate_editor(doc: dict, evidence: dict, template: dict) -> dict:
    if (
        not isinstance(doc, dict)
        or doc.get("type") != "doc"
        or not isinstance(doc.get("content"), list)
    ):
        raise ValueError("Formato editor non valido.")
    if len(json.dumps(doc, ensure_ascii=False)) > 350_000:
        raise ValueError("L'elaborato supera la dimensione consentita.")
    sources = {s["id"]: s for s in evidence.get("sources", [])}
    sections = {s["key"] for s in template["sections"]}
    count = 0

    def walk(node, depth=0):
        nonlocal count
        count += 1
        if depth > 12 or count > 4000 or not isinstance(node, dict):
            raise ValueError("Struttura editor troppo complessa.")
        kind = node.get("type")
        if kind not in {
            "doc",
            "paragraph",
            "heading",
            "text",
            "bulletList",
            "orderedList",
            "listItem",
            "hardBreak",
            "evidencePhoto",
            "table",
            "tableRow",
            "tableCell",
            "tableHeader",
        }:
            raise ValueError("Elemento editor non supportato.")
        attrs = node.get("attrs") or {}
        allowed_attrs = (
            {"sectionKey", "sourceIds", "nature"}
            if kind == "paragraph"
            else {"level", "sectionKey"}
            if kind == "heading"
            else {"sourceId", "caption", "sourceIds", "nature"}
            if kind == "evidencePhoto"
            else {"start"}
            if kind == "orderedList"
            else set()
        )
        if kind in {"tableCell", "tableHeader"}:
            allowed_attrs = {"colspan", "rowspan", "colwidth"}
        if not isinstance(attrs, dict) or set(attrs) - allowed_attrs:
            raise ValueError("Attributi editor non supportati.")
        if attrs.get("sectionKey") and (
            not isinstance(attrs["sectionKey"], str) or attrs["sectionKey"] not in sections
        ):
            raise ValueError("Sezione sconosciuta.")
        if "sourceIds" in attrs:
            if (
                not isinstance(attrs["sourceIds"], list)
                or len(attrs["sourceIds"]) > 40
                or any(not isinstance(s, str) or s not in sources for s in attrs["sourceIds"])
            ):
                raise ValueError("La fonte non appartiene a questo elaborato.")
        if attrs.get("nature") and attrs["nature"] not in {
            "observed",
            "reported",
            "proposed",
            "decided",
            "unverified",
        }:
            raise ValueError("Classificazione dell'affermazione non valida.")
        if kind == "heading" and (
            type(attrs.get("level")) is not int or attrs["level"] not in {1, 2, 3}
        ):
            raise ValueError("Livello titolo non valido.")
        if kind in {"tableCell", "tableHeader"}:
            for key in ("colspan", "rowspan"):
                if type(attrs.get(key, 1)) is not int or not 1 <= attrs.get(key, 1) <= 48:
                    raise ValueError("Dimensione della cella non valida.")
            widths = attrs.get("colwidth")
            if widths is not None and (
                not isinstance(widths, list)
                or len(widths) > 48
                or any(type(w) is not int or not 1 <= w <= 2000 for w in widths)
            ):
                raise ValueError("Larghezze delle celle non valide.")
        if kind == "evidencePhoto":
            source = sources.get(attrs.get("sourceId"))
            if not source or source.get("kind") not in {"photo", "image_attachment"}:
                raise ValueError("Fotografia non disponibile nelle fonti.")
            if (
                not isinstance(attrs.get("caption", ""), str)
                or len(attrs.get("caption", "")) > 1000
            ):
                raise ValueError("Didascalia non valida.")
        if "text" in node and (
            kind != "text" or not isinstance(node["text"], str) or len(node["text"]) > 20_000
        ):
            raise ValueError("Testo editor non valido.")
        marks = node.get("marks", [])
        if not isinstance(marks, list) or len(marks) > 8:
            raise ValueError("Formattazione non valida.")
        for mark in marks:
            if (
                not isinstance(mark, dict)
                or mark.get("type") not in {"bold", "italic", "strike", "code"}
                or mark.get("attrs")
            ):
                raise ValueError("Formattazione non consentita.")
        children = node.get("content", [])
        if not isinstance(children, list):
            raise ValueError("Contenuto editor non valido.")
        allowed_children = {
            "doc": {"paragraph", "heading", "bulletList", "orderedList", "table", "evidencePhoto"},
            "paragraph": {"text", "hardBreak"},
            "heading": {"text", "hardBreak"},
            "bulletList": {"listItem"},
            "orderedList": {"listItem"},
            "listItem": {"paragraph", "bulletList", "orderedList"},
            "table": {"tableRow"},
            "tableRow": {"tableCell", "tableHeader"},
            "tableCell": {"paragraph", "heading", "bulletList", "orderedList"},
            "tableHeader": {"paragraph", "heading", "bulletList", "orderedList"},
        }.get(kind, set())
        for child in children:
            if not isinstance(child, dict) or child.get("type") not in allowed_children:
                raise ValueError("Struttura dei contenuti non valida.")
            walk(child, depth + 1)

    walk(doc)
    return doc


def editor_claims(doc: dict) -> list[dict]:
    result = []

    def text(node):
        return node.get("text", "") + " ".join(text(c) for c in node.get("content", []))

    def walk(node):
        if node.get("type") == "paragraph" and text(node).strip():
            result.append(
                {
                    "text": text(node).strip(),
                    "section_key": (node.get("attrs") or {}).get("sectionKey", ""),
                    "source_ids": (node.get("attrs") or {}).get("sourceIds", []),
                    "nature": (node.get("attrs") or {}).get("nature", "reported"),
                }
            )
        if (
            node.get("type") == "evidencePhoto"
            and (node.get("attrs") or {}).get("caption", "").strip()
        ):
            attrs = node["attrs"]
            result.append(
                {
                    "text": attrs["caption"].strip(),
                    "section_key": "photographs",
                    "source_ids": list(
                        dict.fromkeys([attrs["sourceId"], *attrs.get("sourceIds", [])])
                    ),
                    "nature": attrs.get("nature", "reported"),
                }
            )
        for child in node.get("content", []):
            walk(child)

    walk(doc)
    return result


def local_quality(doc: dict, evidence: dict, template: dict) -> list[dict]:
    validate_editor(doc, evidence, template)
    issues = []
    claims = editor_claims(doc)
    for definition in template["sections"]:
        if definition["required"] and not any(
            c["section_key"] == definition["key"] for c in claims
        ):
            issues.append(
                {
                    "section_key": definition["key"],
                    "text": "",
                    "severity": "blocking",
                    "explanation": f"Sezione obbligatoria priva di contenuto: {definition['label']}",
                }
            )
    for claim in claims:
        if not claim["source_ids"] and claim["nature"] != "unverified":
            issues.append(
                {
                    "section_key": claim["section_key"],
                    "text": claim["text"],
                    "severity": "blocking",
                    "explanation": "Affermazione senza fonte: collegare una fonte o dichiarare esplicitamente il dato.",
                }
            )
    if evidence.get("truncated"):
        issues.append(
            {
                "section_key": "",
                "text": "",
                "severity": "warning",
                "explanation": "Le fonti superano il limite di una generazione. Il documento non rappresenta tutte le registrazioni del periodo.",
            }
        )
    return issues
