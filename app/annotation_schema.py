from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int | None = None
    sheet_name: str | None = None
    character_offset_start: int | None = None
    character_offset_end: int | None = None
    snippet: str
    confidence: float = Field(default=0.0, ge=0, le=1)
    verification_status: Literal["verified", "unverified", "revised"] = "unverified"


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = Field(
        description="Short lowercase entity category, e.g. person, organization, vendor, money, date, location"
    )
    confidence: float = Field(ge=0, le=1)
    citations: list[Citation] = Field(default_factory=list)


class ImportantDate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    citations: list[Citation] = Field(default_factory=list)


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    owner: str | None = None
    deadline: str | None = None
    citations: list[Citation] = Field(default_factory=list)


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    severity: Literal["low", "medium", "high"]
    citations: list[Citation] = Field(default_factory=list)


class PIIDetected(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = False
    types: list[str] = Field(default_factory=list)
    count: int = Field(default=0, ge=0)


class AnnotationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detected_language: str | None = None
    page_count: int | None = None
    sheet_count: int | None = None
    has_tables: bool | None = None


class AnnotationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    document_type: str
    summary: str
    key_entities: list[Entity]
    important_dates: list[ImportantDate] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    metadata: AnnotationMetadata = Field(default_factory=AnnotationMetadata)
    warnings: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    pii_detected: PIIDetected = Field(default_factory=PIIDetected)
