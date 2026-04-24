from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.annotation_schema import AnnotationResult
from app.models import DocumentJob

MAX_PROMPT_TEXT_CHARS = 24_000


class AnnotationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Annotation:
    result: AnnotationResult
    input_tokens: int = 0
    output_tokens: int = 0
    usage: dict[str, Any] = field(default_factory=dict)


class Annotator(ABC):
    @abstractmethod
    def annotate(self, job: DocumentJob, extraction: dict[str, Any]) -> Annotation:
        raise NotImplementedError


def build_annotation_messages(job: DocumentJob, extraction: dict[str, Any]) -> list[dict[str, str]]:
    text = str(extraction.get("text") or "")
    if len(text) > MAX_PROMPT_TEXT_CHARS:
        text = text[:MAX_PROMPT_TEXT_CHARS]

    metadata = extraction.get("metadata") or {}
    source_type = extraction.get("source_type") or job.detected_content_type
    warnings = extraction.get("warnings") or []

    system = (
        "You annotate business documents. Return only the requested structured annotation. "
        "Prefer concise summaries, useful entities, important dates, and practical keywords. "
        "Do not include raw sensitive document text unless it is necessary as a short extracted entity."
    )
    user = (
        f"Filename: {job.original_filename}\n"
        f"Detected content type: {job.detected_content_type}\n"
        f"Extraction source type: {source_type}\n"
        f"Extraction metadata: {metadata}\n"
        f"Extraction warnings: {warnings}\n\n"
        f"Extracted text:\n{text}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def validate_annotation_payload(payload: Any) -> AnnotationResult:
    try:
        return AnnotationResult.model_validate(payload)
    except ValidationError:
        try:
            return AnnotationResult.model_validate(repair_annotation_payload(payload))
        except Exception as exc:
            raise AnnotationError(
                "LLM_SCHEMA_VALIDATION_FAILED",
                f"Annotation result did not match schema after repair: {exc}",
            ) from exc
    except Exception as exc:
        raise AnnotationError(
            "LLM_SCHEMA_VALIDATION_FAILED",
            f"Annotation result did not match schema: {exc}",
        ) from exc


def repair_annotation_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise TypeError("annotation payload is not an object")

    repaired = dict(payload)
    repaired.setdefault("schema_version", "1")
    repaired.setdefault("document_type", "document")
    repaired.setdefault("summary", "")
    repaired["key_entities"] = list(repaired.get("key_entities") or [])
    repaired["important_dates"] = list(repaired.get("important_dates") or [])
    repaired["keywords"] = list(repaired.get("keywords") or [])
    repaired["warnings"] = list(repaired.get("warnings") or [])

    metadata = repaired.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    repaired["metadata"] = {
        "detected_language": metadata.get("detected_language"),
        "page_count": metadata.get("page_count"),
        "sheet_count": metadata.get("sheet_count"),
        "has_tables": metadata.get("has_tables"),
    }

    for entity in repaired["key_entities"]:
        if isinstance(entity, dict) and "confidence" in entity:
            try:
                entity["confidence"] = max(0.0, min(1.0, float(entity["confidence"])))
            except (TypeError, ValueError):
                entity["confidence"] = 0.5

    return repaired
