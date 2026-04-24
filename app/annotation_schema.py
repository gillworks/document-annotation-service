from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Entity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str = Field(
        description="Short lowercase entity category, e.g. person, organization, vendor, money, date, location"
    )
    confidence: float = Field(ge=0, le=1)


class ImportantDate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str


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
    important_dates: list[ImportantDate] = []
    keywords: list[str] = []
    metadata: AnnotationMetadata = Field(default_factory=AnnotationMetadata)
    warnings: list[str] = []
