from datetime import date
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field, StrictBool

DocumentType = Literal[
    "daily_report", "inspection", "coordination", "periodic_report", "photo_report", "issue_report"
]
GraphicStyle = Literal["technical", "corporate", "photographic"]


class StrictSchema(Schema):
    model_config = ConfigDict(extra="forbid")


class CreateRequest(StrictSchema):
    idempotency_key: UUID
    project_id: int = Field(gt=0)
    document_type: DocumentType
    period_start: date
    period_end: date
    style: GraphicStyle | None = None
    language: Literal["it", "en", "fr", "ro", "ru", "ar"] = "it"
    context: str = Field(default="", max_length=4000)


class SaveRequest(StrictSchema):
    version: int = Field(gt=0)
    editor_doc: dict


class ActionRequest(StrictSchema):
    idempotency_key: UUID
    version: int = Field(gt=0)
    action: Literal[
        "generate",
        "verify",
        "preview",
        "rewrite",
        "integrate",
        "refresh",
        "photos",
        "missing",
        "summarize",
        "expand",
        "dictate",
    ]
    instruction: str = Field(default="", max_length=4000)
    section_key: str = Field(default="", max_length=64)
    apply_signature: StrictBool = False
    signature_confirmation: StrictBool = False


class AcceptRequest(StrictSchema):
    version: int = Field(gt=0)
    job_id: UUID


class DeclarationRequest(StrictSchema):
    version: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=4000)
    confirmed: StrictBool


class PublishRequest(StrictSchema):
    version: int = Field(gt=0)
    preview_hash: str = Field(pattern="^[a-f0-9]{64}$")
    confirm_signature: StrictBool = False


class SignatureRequest(StrictSchema):
    strokes: list = Field(max_length=100)


class StyleRequest(StrictSchema):
    style: GraphicStyle
