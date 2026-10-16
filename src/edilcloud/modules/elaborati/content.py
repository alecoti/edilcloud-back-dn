"""One bounded, portable Tiptap schema for web, native editor and PDF."""

import hashlib
import json
import re

from .fields import EditableField, field_source_id, fields_in, validate_field

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
from urllib.parse import urlsplit


def safe_link(value):
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except ValueError:
        return False


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def editor_equivalent(left, right):
    """Recognize only harmless editor defaults, never normalize facts or text.

    Tiptap emits null alignment/widths and unit cell spans on an unchanged open.
    Those defaults must not invalidate a successful, identical-content review.
    """

    def normalized(node):
        result = {k: v for k, v in node.items() if k not in {"attrs", "content"}}
        attrs = {k: v for k, v in (node.get("attrs") or {}).items() if v is not None}
        if attrs.get("factIds") == []:
            attrs.pop("factIds")
        for key, value in {"colspan": 1, "rowspan": 1, "start": 1}.items():
            if attrs.get(key) == value:
                attrs.pop(key)
        if attrs:
            result["attrs"] = attrs
        if node.get("content"):
            result["content"] = [normalized(child) for child in node["content"]]
        if node.get("type") == "table" and result.get("content"):
            rows = result["content"]
            widths = [(c.get("attrs") or {}).get("colwidth") for c in rows[0].get("content", [])]
            for row in rows[1:]:
                for cell, width in zip(row.get("content", []), widths):
                    # ProseMirror propagates the first row's widths to later
                    # cells on its first transaction. The effective layout is
                    # already defined by that first row in editor and PDF.
                    if width and (cell.get("attrs") or {}).get("colwidth") == width:
                        cell["attrs"].pop("colwidth")
                        if not cell["attrs"]:
                            cell.pop("attrs")
        return result

    return normalized(left) == normalized(right)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(StrictModel):
    text: str = Field(min_length=1)
    source_ids: list[str]
    nature: str = Field(pattern="^(observed|reported|proposed|decided|unverified)$")
    fields: list[EditableField] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def placeholders_match(self):
        keys = [field.key for field in self.fields]
        tokens = re.findall(r"\{\{([a-z][a-z0-9_.-]{0,99})\}\}", self.text)
        if len(set(keys)) != len(keys) or sorted(tokens) != sorted(keys):
            raise ValueError(
                "Ogni placeholder deve avere una definizione e comparire una sola volta."
            )
        return self


class Finding(StrictModel):
    """Factual selection is separate from the writer's editable input fields."""

    key: str = Field(max_length=64)
    text: str = Field(min_length=1)
    source_ids: list[str]
    nature: str = Field(pattern="^(observed|reported|proposed|decided|unverified)$")


class ReasoningResult(StrictModel):
    facts: list[Finding]
    duplicates: list[str]
    contradictions: list[str]
    missing_data: list[str]


class ClaimList(StrictModel):
    style: Literal["bullet", "ordered"]
    items: list[Claim] = Field(min_length=1)


class ClaimCell(StrictModel):
    paragraphs: list[Claim] = Field(min_length=1)


class ClaimTable(StrictModel):
    columns: list[str] = Field(min_length=2, max_length=6)
    rows: list[list[Claim | ClaimCell]] = Field(min_length=1)
    widths: list[int] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def rectangular(self):
        if any(not column.strip() or len(column) > 100 for column in self.columns):
            raise ValueError("Intestazione della tabella non valida.")
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("La tabella deve avere lo stesso numero di celle per riga.")
        if self.widths and (
            len(self.widths) != len(self.columns) or any(w < 1 or w > 100 for w in self.widths)
        ):
            raise ValueError("Le proporzioni devono corrispondere alle colonne della tabella.")
        return self


class BlockPlacement(StrictModel):
    kind: Literal["paragraph", "list", "table", "photo", "heading"]
    index: int = Field(default=0, ge=0)
    label: str = Field(default="", max_length=180)
    heading_level: Literal[3, 4, 5, 6] = 3


class Section(StrictModel):
    key: str = Field(max_length=64)
    paragraphs: list[Claim]
    lists: list[ClaimList] = Field(default_factory=list)
    tables: list[ClaimTable] = Field(default_factory=list)
    layout: list[BlockPlacement] = Field(default_factory=list)


class Photograph(StrictModel):
    source_id: str
    caption: Claim
    section_key: str = ""
    title: str = Field(default="", max_length=180)
    layout: Literal["full", "half"] = "full"


class Composition(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    subtitle: str = Field(default="", max_length=500)
    sections: list[Section]
    photographs: list[Photograph]


class QualityIssue(StrictModel):
    section_key: str
    text: str
    severity: str = Field(pattern="^(warning|blocking)$")
    explanation: str


class QualityResult(StrictModel):
    issues: list[QualityIssue]
    missing_data: list[str]


def editor_from_composition(composition: Composition, template: dict) -> dict:
    expected = [s["key"] for s in template["sections"]]
    if [s.key for s in composition.sections] != expected:
        raise ValueError("Le sezioni generate non rispettano il template.")

    def paragraph(claim, section_key):
        inline = []
        fields = {field.key: field for field in claim.fields}
        cursor = 0
        for match in re.finditer(r"\{\{([a-z][a-z0-9_.-]{0,99})\}\}", claim.text):
            if match.start() > cursor:
                inline.append({"type": "text", "text": claim.text[cursor : match.start()]})
            field = fields[match[1]]
            inline.append(
                {
                    "type": "documentField",
                    "attrs": {
                        "fieldId": field.key,
                        "label": field.label,
                        "kind": field.kind,
                        "unit": field.unit,
                        "value": "",
                        "personSourceId": "",
                    },
                }
            )
            cursor = match.end()
        if cursor < len(claim.text):
            inline.append({"type": "text", "text": claim.text[cursor:]})
        return {
            "type": "paragraph",
            "attrs": {
                "sectionKey": section_key,
                "sourceIds": claim.source_ids,
                "nature": claim.nature,
                **({"factIds": claim.fact_ids} if claim.fact_ids else {}),
            },
            "content": inline,
        }

    content = []

    def photo_node(photo):
        return {
            "type": "evidencePhoto",
            "attrs": {
                "sourceId": photo.source_id,
                "caption": photo.caption.text,
                "sourceIds": photo.caption.source_ids,
                "nature": photo.caption.nature,
                **({"factIds": photo.caption.fact_ids} if photo.caption.fact_ids else {}),
                "sectionKey": photo.section_key or None,
                "title": photo.title,
                "layout": photo.layout,
            },
        }

    if any(p.section_key and p.section_key not in expected for p in composition.photographs):
        raise ValueError("Sezione della fotografia sconosciuta.")
    for definition, section in zip(template["sections"], composition.sections, strict=True):
        content.append(
            {
                "type": "heading",
                "attrs": {"level": 2, "sectionKey": section.key},
                "content": [{"type": "text", "text": definition["label"]}],
            }
        )
        start = len(content)
        for claim in section.paragraphs:
            content.append(paragraph(claim, section.key))
        for listing in section.lists:
            content.append(
                {
                    "type": "orderedList" if listing.style == "ordered" else "bulletList",
                    "content": [
                        {"type": "listItem", "content": [paragraph(claim, section.key)]}
                        for claim in listing.items
                    ],
                }
            )
        for table in section.tables:
            header = {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableHeader",
                        "content": [
                            paragraph(
                                Claim(text=column, source_ids=[], nature="unverified"), section.key
                            )
                        ],
                    }
                    for column in table.columns
                ],
            }
            rows = [
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableCell",
                            "content": [
                                paragraph(claim, section.key)
                                for claim in (
                                    cell.paragraphs if isinstance(cell, ClaimCell) else [cell]
                                )
                            ],
                        }
                        for cell in row
                    ],
                }
                for row in table.rows
            ]
            content.append({"type": "table", "content": [header, *rows]})
            if table.widths:
                for cell, width in zip(header["content"], table.widths, strict=True):
                    cell["attrs"] = {"colwidth": [width * 10]}
        content.extend(
            photo_node(photo)
            for photo in composition.photographs
            if photo.section_key == section.key
        )
        if section.layout:
            ordered = {"paragraph": [], "list": [], "table": [], "photo": []}
            kinds = {
                "paragraph": "paragraph",
                "bulletList": "list",
                "orderedList": "list",
                "table": "table",
                "evidencePhoto": "photo",
            }
            for node in content[start:]:
                ordered[kinds[node["type"]]].append(node)
            arranged = []
            seen = set()
            for block in section.layout:
                if block.kind == "heading":
                    if not block.label.strip():
                        raise ValueError("Il titolo del gruppo documentale è vuoto.")
                    arranged.append(
                        {
                            "type": "heading",
                            "attrs": {"level": block.heading_level},
                            "content": [{"type": "text", "text": block.label}],
                        }
                    )
                else:
                    identity = (block.kind, block.index)
                    if identity in seen or block.index >= len(ordered[block.kind]):
                        raise ValueError("Ordine dei blocchi documentali non valido.")
                    seen.add(identity)
                    arranged.append(ordered[block.kind][block.index])
            expected_blocks = {
                (kind, i) for kind, nodes in ordered.items() for i in range(len(nodes))
            }
            if seen != expected_blocks:
                raise ValueError("L'ordine del documento omette contenuti generati.")
            content[start:] = arranged
    for photo in composition.photographs:
        if not photo.section_key:
            content.append(photo_node(photo))
    return {
        "type": "doc",
        "attrs": {"documentTitle": composition.title, "subtitle": composition.subtitle},
        "content": content,
    }


def validate_editor(doc: dict, evidence: dict, template: dict) -> dict:
    from django.conf import settings

    if (
        not isinstance(doc, dict)
        or doc.get("type") != "doc"
        or not isinstance(doc.get("content"), list)
    ):
        raise ValueError("Formato editor non valido.")
    if len(json.dumps(doc, ensure_ascii=False).encode("utf8")) > settings.ELABORATI_EDITOR_MAX_BYTES:
        raise ValueError("L'elaborato supera la dimensione consentita.")
    sources = {s["id"]: s for s in evidence.get("sources", [])}
    fact_ids = set(evidence.get("fact_ids", []))
    sections = {s["key"] for s in template["sections"]}
    count = 0
    field_ids = set()

    def walk(node, depth=0):
        nonlocal count
        count += 1
        if depth > 12 or count > settings.ELABORATI_EDITOR_MAX_NODES or not isinstance(node, dict):
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
            "documentField",
        }:
            raise ValueError("Elemento editor non supportato.")
        attrs = node.get("attrs") or {}
        allowed_attrs = (
            {"sectionKey", "sourceIds", "factIds", "nature", "textAlign"}
            if kind == "paragraph"
            else {"level", "sectionKey", "textAlign"}
            if kind == "heading"
            else {"sourceId", "caption", "sourceIds", "factIds", "nature", "sectionKey", "title", "layout"}
            if kind == "evidencePhoto"
            else {"start", "type"}
            if kind == "orderedList"
            else set()
        )
        if kind in {"tableCell", "tableHeader"}:
            allowed_attrs = {"colspan", "rowspan", "colwidth"}
        if kind == "documentField":
            allowed_attrs = {"fieldId", "label", "kind", "unit", "value", "personSourceId"}
        if kind == "doc":
            allowed_attrs = {"documentTitle", "subtitle"}
        if not isinstance(attrs, dict) or set(attrs) - allowed_attrs:
            raise ValueError("Attributi editor non supportati.")
        if kind == "doc" and any(
            not isinstance(attrs.get(key, ""), str) or len(attrs.get(key, "")) > limit
            for key, limit in (("documentTitle", 255), ("subtitle", 500))
        ):
            raise ValueError("Titolo o sottotitolo del documento non valido.")
        if kind == "documentField":
            validate_field(attrs, sources)
            if attrs["fieldId"] in field_ids:
                raise ValueError("Identificatore di campo duplicato nel documento.")
            field_ids.add(attrs["fieldId"])
        alignment = attrs.get("textAlign")
        if alignment is not None and (
            not isinstance(alignment, str)
            or alignment not in {"left", "center", "right", "justify"}
        ):
            raise ValueError("Allineamento non supportato.")
        if attrs.get("sectionKey") and (
            not isinstance(attrs["sectionKey"], str) or attrs["sectionKey"] not in sections
        ):
            raise ValueError("Sezione sconosciuta.")
        if "factIds" in attrs:
            if not isinstance(attrs["factIds"], list) or any(
                not isinstance(f, str) or f not in fact_ids for f in attrs["factIds"]
            ):
                raise ValueError("Riferimento a un fatto documentale non valido.")
        if "sourceIds" in attrs:
            if not isinstance(attrs["sourceIds"], list) or any(
                not isinstance(s, str) or s not in sources for s in attrs["sourceIds"]
            ):
                raise ValueError("La fonte non appartiene a questo elaborato.")
        if "nature" in attrs and (
            not isinstance(attrs["nature"], str)
            or attrs["nature"]
            not in {
                "observed",
                "reported",
                "proposed",
                "decided",
                "unverified",
            }
        ):
            raise ValueError("Classificazione dell'affermazione non valida.")
        if kind == "orderedList" and (
            type(attrs.get("start", 1)) is not int or not 1 <= attrs.get("start", 1) <= 1_000_000
        ):
            raise ValueError("Numerazione dell'elenco non valida.")
        # Tiptap 2 emits type=null even for an unchanged, ordinary numbered list.
        # Accept only the HTML numbering styles, never arbitrary DOM attributes.
        if kind == "orderedList" and attrs.get("type") is not None and (
            not isinstance(attrs["type"], str)
            or attrs["type"] not in {"1", "a", "A", "i", "I"}
        ):
            raise ValueError("Stile di numerazione dell'elenco non valido.")
        if kind == "heading" and (
            type(attrs.get("level")) is not int or attrs["level"] not in {1, 2, 3, 4, 5, 6}
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
            source_id = attrs.get("sourceId")
            source = sources.get(source_id) if isinstance(source_id, str) else None
            if not source or source.get("kind") not in {"photo", "image_attachment"}:
                raise ValueError("Fotografia non disponibile nelle fonti.")
            if not isinstance(attrs.get("caption", ""), str):
                raise ValueError("Didascalia non valida.")
            if (
                attrs.get("layout", "full") not in {"full", "half"}
                or not isinstance(attrs.get("title", ""), str)
                or len(attrs.get("title", "")) > 180
            ):
                raise ValueError("Formato della fotografia non valido.")
        if "text" in node and (kind != "text" or not isinstance(node["text"], str)):
            raise ValueError("Testo editor non valido.")
        marks = node.get("marks", [])
        if not isinstance(marks, list) or len(marks) > 8:
            raise ValueError("Formattazione non valida.")
        for mark in marks:
            if not isinstance(mark, dict) or mark.get("type") not in {
                "bold",
                "italic",
                "underline",
                "strike",
                "code",
                "highlight",
                "link",
            }:
                raise ValueError("Formattazione non consentita.")
            mark_attrs = mark.get("attrs") or {}
            if not isinstance(mark_attrs, dict):
                raise ValueError("Formattazione non consentita.")
            if mark["type"] == "link":
                if set(mark_attrs) - {"href", "target", "rel", "class"} or not safe_link(
                    mark_attrs.get("href")
                ):
                    raise ValueError(
                        "Collegamento non valido: usare un indirizzo HTTP o HTTPS completo."
                    )
                if (
                    mark_attrs.get("target") not in {None, "_blank", "_self"}
                    or mark_attrs.get("class") is not None
                ):
                    raise ValueError("Attributi del collegamento non validi.")
                if mark_attrs.get("rel") is not None and (
                    not isinstance(mark_attrs["rel"], str)
                    or set(mark_attrs["rel"].split()) - {"noopener", "noreferrer", "nofollow"}
                ):
                    raise ValueError("Attributi del collegamento non validi.")
            elif mark["type"] == "highlight":
                if set(mark_attrs) - {"color"} or mark_attrs.get("color") not in {
                    None,
                    "#fef3c7",
                    "#dcfce7",
                }:
                    raise ValueError("Evidenziatura non valida.")
            elif mark_attrs:
                raise ValueError("Formattazione non consentita.")
        children = node.get("content", [])
        if not isinstance(children, list):
            raise ValueError("Contenuto editor non valido.")
        allowed_children = {
            "doc": {"paragraph", "heading", "bulletList", "orderedList", "table", "evidencePhoto"},
            "paragraph": {"text", "hardBreak", "documentField"},
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


def editor_claims(doc: dict, *, include_context=False) -> list[dict]:
    result = []

    def text(node):
        if node.get("type") == "documentField":
            field = node["attrs"]
            return field.get("value") or f"[Da compilare: {field['label']}]"
        return node.get("text", "") + " ".join(text(c) for c in node.get("content", []))

    def walk(node, context=None):
        if node.get("type") == "tableHeader":
            # Column labels carry no factual assertion and must not inflate the
            # missing-data count or be sent to the verifier as unsupported facts.
            return
        if node.get("type") == "paragraph" and text(node).strip():
            fields = list(fields_in(node))
            if (
                fields
                and all(f["kind"] == "signature" and not f.get("value") for f in fields)
                and all(
                    child.get("type") != "text" or not child.get("text", "").strip()
                    for child in node.get("content", [])
                )
            ):
                # A blank signature space is neither a fact nor substantive
                # content satisfying a required documentary section.
                return
            field_refs = [field_source_id(f) for f in fields if f.get("value")]
            attrs = node.get("attrs") or {}
            only_empty_fields = (
                fields
                and all(not f.get("value") for f in fields)
                and all(
                    c.get("type") != "text" or not c.get("text", "").strip()
                    for c in node.get("content", [])
                )
            )
            result.append(
                {
                    "text": text(node).strip(),
                    "section_key": (node.get("attrs") or {}).get("sectionKey", ""),
                    "source_ids": list(dict.fromkeys([*attrs.get("sourceIds", []), *field_refs])),
                    "nature": "unverified"
                    if only_empty_fields
                    else attrs.get("nature", "reported"),
                    "document_fields": fields,
                    **({"fact_ids": attrs["factIds"]} if attrs.get("factIds") else {}),
                    **(context or {}),
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
                    **({"fact_ids": attrs["factIds"]} if attrs.get("factIds") else {}),
                }
            )
        if include_context and node.get("type") == "table":
            rows = node.get("content", [])
            headers = [text(cell).strip() for cell in rows[0].get("content", [])] if rows else []
            for row in rows:
                cells = row.get("content", [])
                row_text = [text(cell).strip() for cell in cells]
                for index, cell in enumerate(cells):
                    walk(cell, {"table_column": headers[index] if index < len(headers) else "",
                                "table_row": row_text})
            return
        for child in node.get("content", []):
            walk(child, context)

    walk(doc)
    return result


def local_quality(doc: dict, evidence: dict, template: dict) -> list[dict]:
    validate_editor(doc, evidence, template)
    issues = []
    from .fields import field_quality

    issues.extend(field_quality(doc, evidence))
    claims = editor_claims(doc)
    from .fields import editable_context_issues

    issues.extend(editable_context_issues(claims))
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
    from .editorial import repetition_issues

    issues.extend(repetition_issues(claims))
    return issues


def composition_claims(composition):
    """Validate provenance equally for prose, lists, tables and photo captions."""
    for section in composition.sections:
        yield from section.paragraphs
        for listing in section.lists:
            yield from listing.items
        for table in section.tables:
            for row in table.rows:
                for cell in row:
                    yield from cell.paragraphs if isinstance(cell, ClaimCell) else [cell]
    yield from (photo.caption for photo in composition.photographs)
