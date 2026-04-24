import pytest
from pydantic import ValidationError

from app.annotation_schema import AnnotationResult
from app.annotators.base import (
    SINGLE_CALL_CITATION_WARNING,
    enforce_single_call_citation_provenance,
    validate_annotation_payload,
)


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
    assert result.key_entities[0].citations == []
    assert result.action_items == []
    assert result.risks == []
    assert result.pii_detected.present is False


def test_annotation_schema_accepts_agent_payload_with_citations() -> None:
    result = AnnotationResult.model_validate(
        {
            "schema_version": "1",
            "document_type": "contract",
            "summary": "Agreement with payment and termination terms.",
            "key_entities": [
                {
                    "name": "Northwind Traders LLC",
                    "type": "organization",
                    "confidence": 0.91,
                    "citations": [
                        {
                            "page_number": 1,
                            "snippet": "Northwind Traders LLC agrees to the payment terms.",
                            "confidence": 0.88,
                            "verification_status": "verified",
                        }
                    ],
                }
            ],
            "important_dates": [
                {
                    "label": "effective_date",
                    "value": "2026-04-24",
                    "citations": [
                        {
                            "page_number": 1,
                            "snippet": "Effective Date: 2026-04-24",
                            "confidence": 0.85,
                        }
                    ],
                }
            ],
            "action_items": [
                {
                    "description": "Review payment terms.",
                    "owner": "Finance",
                    "deadline": "2026-05-01",
                    "citations": [
                        {
                            "page_number": 2,
                            "snippet": "Payment is due within 30 days.",
                            "confidence": 0.8,
                        }
                    ],
                }
            ],
            "risks": [
                {
                    "description": "Late payment penalty may apply.",
                    "severity": "medium",
                    "citations": [
                        {
                            "page_number": 2,
                            "snippet": "Late payments accrue interest.",
                            "confidence": 0.76,
                        }
                    ],
                }
            ],
            "pii_detected": {"present": True, "types": ["email", "phone"], "count": 2},
        }
    )

    assert result.key_entities[0].citations[0].verification_status == "verified"
    assert result.action_items[0].citations[0].snippet == "Payment is due within 30 days."
    assert result.risks[0].severity == "medium"
    assert result.pii_detected.types == ["email", "phone"]


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


def test_annotation_schema_rejects_invalid_agent_fields() -> None:
    with pytest.raises(ValidationError):
        AnnotationResult.model_validate(
            {
                "schema_version": "1",
                "document_type": "contract",
                "summary": "Contract.",
                "key_entities": [
                    {
                        "name": "Acme Corporation",
                        "type": "organization",
                        "confidence": 0.9,
                        "citations": [
                            {
                                "page_number": 1,
                                "snippet": "Acme Corporation",
                                "confidence": 1.5,
                            }
                        ],
                    }
                ],
                "risks": [{"description": "Bad term.", "severity": "critical"}],
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
    assert result.key_entities[0].citations == []
    assert result.metadata.page_count == 1


def test_single_call_modes_preserve_fields_but_downgrade_citations() -> None:
    result = validate_annotation_payload(
        {
            "document_type": "contract",
            "summary": "Contract with payment terms.",
            "key_entities": [
                {
                    "name": "Acme Corporation",
                    "type": "organization",
                    "confidence": 0.9,
                    "citations": [
                        {
                            "page_number": 1,
                            "snippet": "Acme Corporation pays invoices within 30 days.",
                            "confidence": 0.8,
                            "verification_status": "verified",
                        }
                    ],
                }
            ],
            "important_dates": [
                {
                    "label": "due_date",
                    "value": "2026-05-24",
                    "citations": [
                        {
                            "page_number": 2,
                            "snippet": "Payment is due within 30 days.",
                            "confidence": 0.8,
                        }
                    ],
                }
            ],
            "action_items": [{"description": "Review payment terms."}],
            "risks": [
                {
                    "description": "Late payment interest applies.",
                    "severity": "medium",
                    "citations": [
                        {
                            "page_number": 3,
                            "snippet": "Late payments accrue interest.",
                            "confidence": 0.8,
                            "verification_status": "revised",
                        }
                    ],
                }
            ],
            "pii_detected": {"present": True, "types": ["email"], "count": 1},
        }
    )

    coerced = enforce_single_call_citation_provenance(result)

    assert coerced.key_entities[0].citations[0].verification_status == "unverified"
    assert coerced.important_dates[0].citations[0].verification_status == "unverified"
    assert coerced.risks[0].citations[0].verification_status == "unverified"
    assert coerced.action_items[0].description == "Review payment terms."
    assert coerced.risks[0].severity == "medium"
    assert coerced.pii_detected.present is True
    assert SINGLE_CALL_CITATION_WARNING in coerced.warnings
