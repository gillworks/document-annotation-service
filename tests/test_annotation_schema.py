import pytest
from pydantic import ValidationError

from app.annotation_schema import AnnotationResult
from app.annotators.base import validate_annotation_payload


def test_annotation_schema_accepts_expected_payload() -> None:
    result = AnnotationResult.model_validate(
        {
            "schema_version": "1",
            "document_type": "invoice",
            "summary": "Invoice for services.",
            "key_entities": [
                {"name": "Acme Corporation", "type": "organization", "confidence": 0.91}
            ],
            "important_dates": [{"label": "due_date", "value": "2026-05-24"}],
            "keywords": ["invoice", "payment"],
            "metadata": {
                "detected_language": "en",
                "page_count": 1,
                "sheet_count": None,
                "has_tables": True,
            },
            "warnings": [],
        }
    )

    assert result.schema_version == "1"
    assert result.key_entities[0].confidence == 0.91


def test_annotation_schema_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        AnnotationResult.model_validate(
            {
                "schema_version": "1",
                "document_type": "invoice",
                "summary": "Invoice for services.",
                "key_entities": [
                    {"name": "Acme Corporation", "type": "organization", "confidence": 1.5}
                ],
            }
        )


def test_annotation_payload_repair_clamps_entity_confidence() -> None:
    result = validate_annotation_payload(
        {
            "document_type": "invoice",
            "summary": "Invoice for services.",
            "key_entities": [
                {"name": "Acme Corporation", "type": "organization", "confidence": 2}
            ],
            "metadata": {"page_count": 1, "has_tables": True, "ignored": "value"},
        }
    )

    assert result.schema_version == "1"
    assert result.key_entities[0].confidence == 1.0
    assert result.metadata.page_count == 1
