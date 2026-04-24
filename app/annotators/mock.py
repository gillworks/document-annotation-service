import re
from typing import Any

from app.annotation_schema import AnnotationMetadata, AnnotationResult, Entity, ImportantDate
from app.annotators.base import Annotation, Annotator
from app.models import DocumentJob


class MockAnnotator(Annotator):
    def annotate(self, job: DocumentJob, extraction: dict[str, Any]) -> Annotation:
        text = str(extraction.get("text") or "")
        metadata = extraction.get("metadata") or {}
        source_type = str(extraction.get("source_type") or "document")
        document_type = infer_document_type(job.original_filename, text, source_type)
        entities = infer_entities(job.original_filename, text)
        dates = infer_dates(text)
        summary = build_summary(document_type, job.original_filename, text)

        result = AnnotationResult(
            document_type=document_type,
            summary=summary,
            key_entities=entities,
            important_dates=dates,
            keywords=infer_keywords(document_type, text),
            metadata=AnnotationMetadata(
                detected_language="en" if text else None,
                page_count=metadata.get("page_count"),
                sheet_count=metadata.get("sheet_count"),
                has_tables=metadata.get("has_tables"),
            ),
            warnings=["annotator: mock mode - result is synthetic"],
        )
        return Annotation(
            result=result,
            input_tokens=0,
            output_tokens=0,
            usage={
                "provider": "mock",
                "annotator_mode": "mock",
                "model": "mock",
                "estimated_cost_usd": 0.0,
            },
        )


def infer_document_type(filename: str, text: str, source_type: str) -> str:
    haystack = f"{filename}\n{text}".lower()
    if "invoice" in haystack or "amount due" in haystack or "total due" in haystack:
        return "invoice"
    if source_type in {"csv", "xlsx"}:
        return "spreadsheet"
    if "report" in haystack:
        return "report"
    return "document"


def infer_entities(filename: str, text: str) -> list[Entity]:
    entities = [Entity(name=filename, type="filename", confidence=1.0)]
    organizations = re.findall(
        r"\b[A-Z][A-Za-z]+(?:[ \t]+[A-Z][A-Za-z]+)*[ \t]+(?:Corporation|LLC|Inc|Enterprises|Labs|Analytics)\b",
        text,
    )
    for name in dedupe(organizations)[:4]:
        entities.append(Entity(name=name, type="organization", confidence=0.74))

    money_values = re.findall(r"\$[0-9][0-9,]*(?:\.[0-9]{2})?", text)
    for value in dedupe(money_values)[:3]:
        entities.append(Entity(name=value, type="money", confidence=0.7))

    return entities[:8]


def infer_dates(text: str) -> list[ImportantDate]:
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4}\b",
    ]
    values: list[str] = []
    for pattern in patterns:
        values.extend(re.findall(pattern, text))
    return [
        ImportantDate(label=f"date_{index}", value=value)
        for index, value in enumerate(dedupe(values)[:5], start=1)
    ]


def infer_keywords(document_type: str, text: str) -> list[str]:
    keywords = [document_type]
    for candidate in ("invoice", "payment", "total", "email", "date", "amount", "customer", "vendor"):
        if candidate in text.lower() and candidate not in keywords:
            keywords.append(candidate)
    return keywords[:8]


def build_summary(document_type: str, filename: str, text: str) -> str:
    cleaned = " ".join(text.split())
    if cleaned:
        return f"Synthetic {document_type} annotation for {filename}: {cleaned[:220]}"
    return f"Synthetic {document_type} annotation for {filename}."


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    output = []
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            output.append(normalized)
    return output
