"""Revision-scoped editable documentary fields, never operational site records."""

import re
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal


FieldKind = Literal["text", "person", "company", "date", "time", "hours", "quantity", "signature"]


class EditableField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,99}$")
    label: str = Field(min_length=1, max_length=180)
    kind: FieldKind
    unit: str = Field(default="", max_length=30)


def fields_in(doc):
    if doc.get("type") == "documentField":
        yield doc["attrs"]
    for child in doc.get("content", []):
        yield from fields_in(child)


def ensure_signature_slot(doc, template, language):
    """The unfilled signature space belongs to the editable document itself."""
    if any(field["kind"] == "signature" for field in fields_in(doc)):
        return doc
    labels = {
        "it": "Firma del redattore da acquisire",
        "en": "Author signature pending",
        "fr": "Signature du rédacteur à recueillir",
        "ro": "Semnătura redactorului de colectat",
        "ru": "Ожидается подпись составителя",
        "ar": "توقيع مُعدّ المستند مطلوب",
    }
    doc["content"].append(
        {
            "type": "paragraph",
            "attrs": {
                "sectionKey": template["sections"][-1]["key"],
                "sourceIds": [],
                "nature": "unverified",
            },
            "content": [
                {
                    "type": "documentField",
                    "attrs": {
                        "fieldId": "document_author_signature",
                        "label": labels.get(language, labels["en"]),
                        "kind": "signature",
                        "unit": "",
                        "value": "",
                        "personSourceId": "",
                    },
                }
            ],
        }
    )
    return doc


def declaration_id(field):
    return f"field.{field['fieldId']}"


def field_source_id(field):
    return f"declaration:{declaration_id(field)}"


def field_text(field):
    value = field.get("value", "")
    return f"{field['label']}: {value}{' ' + field['unit'] if field.get('unit') else ''}"


def validate_field(attrs, sources):
    EditableField.model_validate(
        {
            "key": attrs.get("fieldId"),
            "label": attrs.get("label"),
            "kind": attrs.get("kind"),
            "unit": attrs.get("unit", ""),
        }
    )
    value = attrs.get("value", "")
    person = attrs.get("personSourceId", "")
    if not isinstance(value, str) or len(value) > 4000 or not isinstance(person, str):
        raise ValueError("Valore del campo documentale non valido.")
    if attrs["kind"] == "signature" and (value or person):
        raise ValueError("La firma richiede il percorso esplicito di sottoscrizione.")
    if person:
        source = sources.get(person)
        if (
            attrs["kind"] != "person"
            or not source
            or source.get("kind") != "member"
            or source["data"].get("name") != value
        ):
            raise ValueError("La persona collegata non appartiene alle fonti di questo cantiere.")
    if value and attrs["kind"] in {"hours", "quantity"}:
        try:
            number = Decimal(value.replace(",", "."))
            if not number.is_finite() or number < 0:
                raise InvalidOperation
        except InvalidOperation as exc:
            raise ValueError("Inserire un numero positivo o zero, senza unità nel valore.") from exc
    if value and attrs["kind"] == "date":
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Inserire una data nel formato anno-mese-giorno.") from exc
    if value and attrs["kind"] == "time" and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("Inserire un orario nel formato ore:minuti.")


def sync_field_declarations(*, revision, profile, doc):
    """Attribute changed values on the server; clients cannot choose the declarant.

    Replacing/clearing a value replaces/removes only its current revision source.
    Published revisions keep their frozen declarations and evidence unchanged.
    """
    from django.utils import timezone
    from edilcloud.modules.projects.services import profile_display_name
    from .content import digest

    prior = {d["field_id"]: d for d in revision.declarations if d.get("field_id")}
    declarations = [d for d in revision.declarations if not d.get("field_id")]
    active = []
    for field in fields_in(doc):
        if not field.get("value"):
            continue
        old = prior.get(field["fieldId"])
        fingerprint = digest(
            {
                k: field.get(k, "")
                for k in ("fieldId", "kind", "label", "value", "unit", "personSourceId")
            }
        )
        if old and old.get("field_hash") == fingerprint:
            declaration = old
        else:
            declaration = {
                "id": declaration_id(field),
                "text": field_text(field),
                "author": profile_display_name(profile),
                "profile_id": profile.pk,
                "at": timezone.now().isoformat(),
                "field_id": field["fieldId"],
                "field_hash": fingerprint,
                "field": deepcopy(field),
            }
        active.append(declaration)
    revision.declarations = [*declarations, *active]
    evidence = deepcopy(revision.evidence)
    old_ids = {f"declaration:{d['id']}" for d in prior.values()}
    evidence["sources"] = [s for s in evidence.get("sources", []) if s["id"] not in old_ids]
    for declaration in active:
        source = {
            "id": f"declaration:{declaration['id']}",
            "kind": "declaration",
            "record_id": declaration["id"],
            "parent_id": None,
            "at": declaration["at"],
            "data": {
                "text": declaration["text"],
                "declared_by": declaration["author"],
                "declared_at": declaration["at"],
                "nature": "reported",
                "document_field": declaration["field"],
            },
        }
        source["hash"] = digest(source)
        evidence["sources"].append(source)
    evidence.pop("bundle_hash", None)
    evidence["bundle_hash"] = digest(evidence)
    revision.evidence = evidence


def field_quality(doc, evidence):
    from .content import digest

    sources = {s["id"]: s for s in evidence.get("sources", [])}
    issues = []
    for field in fields_in(doc):
        if field.get("value"):
            source = sources.get(field_source_id(field), {})
            if digest(source.get("data", {}).get("document_field")) != digest(field):
                issues.append(
                    {
                        "section_key": "",
                        "text": field_text(field),
                        "severity": "blocking",
                        "explanation": "Il valore deve essere salvato come dichiarazione del redattore.",
                    }
                )
        elif field["kind"] != "signature":
            issues.append(
                {
                    "section_key": "",
                    "text": field["label"],
                    "severity": "warning",
                    "explanation": "Campo da completare, mantenuto visibile nel documento.",
                }
            )
    return issues


def editable_context_issues(claims):
    """Ask the writer to remove missing-data prose that survives completion."""
    pattern = re.compile(
        r"non (?:sono |è |risultano |risulta )?documentat|not (?:documented|recorded)|"
        r"pas document|non documenté|nu (?:sunt |este )?document|не (?:зафикс|документ)|غير موثق",
        re.IGNORECASE,
    )
    return [
        {
            "section_key": claim["section_key"],
            "text": claim["text"],
            "severity": "warning",
            "category": "editable_context",
            "explanation": "Il testo attorno al campo ripete che il dato non è documentato e rimarrebbe invariato dopo la compilazione. Usa una formulazione neutra o il solo campo etichettato, mantenendo le lacune nelle loro sedi.",
        }
        for claim in claims
        if claim.get("document_fields")
        and any(f["kind"] != "signature" for f in claim["document_fields"])
        and pattern.search(claim["text"])
    ]


def preserve_completed_fields(previous, proposal):
    """AI may restructure prose but cannot silently discard manual completion."""
    prior = {f["fieldId"]: f for f in fields_in(previous) if f.get("value")}
    following = {f["fieldId"]: f for f in fields_in(proposal)}
    if set(prior) - set(following):
        raise ValueError(
            "La proposta omette campi già compilati. La bozza originale resta intatta."
        )
    for key, field in prior.items():
        frozen = deepcopy(field)
        following[key].clear()
        following[key].update(frozen)
    return proposal
