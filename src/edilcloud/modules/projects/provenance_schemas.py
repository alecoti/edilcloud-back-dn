from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field


class ParticipationRequest(Schema):
    model_config = ConfigDict(extra="forbid")
    profile_id: int | None = None
    person_id: UUID | None = None
    company_id: UUID | None = None
    person_name: str = Field(min_length=1, max_length=255)
    company_name: str = Field(min_length=1, max_length=255)
    tax_id: str = Field(default="", max_length=40)
    qualification: str = Field(default="", max_length=255)
    function: str = Field(default="", max_length=255)
    role_codes: list[str] = Field(default_factory=list, max_length=30)
    valid_from: str | None = None
    valid_to: str | None = None
    status: str = "declared"
    appointment_reference: str = Field(default="", max_length=1000)


class CloseParticipationRequest(Schema):
    model_config = ConfigDict(extra="forbid")
    valid_to: str | None = None


class EvidenceMetadataRequest(Schema):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(pattern=r"^[a-f0-9]{64}$")
    photographer_participation_id: UUID | None = None
    declared_content_date: str = Field(default="", max_length=50)
    area: str = Field(default="", max_length=255)
    related_sources: list[UUID] = Field(default_factory=list, max_length=30)
