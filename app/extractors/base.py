from typing import Any, Literal

from pydantic import BaseModel, Field


MAX_EXTRACTED_TEXT_CHARS = 60_000
MAX_SAMPLE_ROWS = 25


class ExtractionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ExtractionPayload(BaseModel):
    schema_version: Literal["extraction.v1"] = "extraction.v1"
    source_type: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    pages: list[dict[str, Any]] = Field(default_factory=list)
    sheets: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def truncate_text(text: str, max_chars: int = MAX_EXTRACTED_TEXT_CHARS) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def stringify_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
