from types import SimpleNamespace
from uuid import uuid4

from app.annotation_schema import AnnotationResult
from app.annotators.base import SINGLE_CALL_CITATION_WARNING
from app.config import Settings


def test_openai_single_call_forces_citations_unverified(monkeypatch) -> None:
    from app.annotators import openai

    class FakeOpenAI:
        def __init__(self, api_key=None, timeout=None):
            self.responses = SimpleNamespace(parse=self.parse)

        def parse(self, **kwargs):
            usage = SimpleNamespace(input_tokens=10, output_tokens=5)
            return SimpleNamespace(output_parsed=AnnotationResult.model_validate(rich_payload()), usage=usage)

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    annotator = openai.OpenAIAnnotator(
        Settings(
            _env_file=None,
            annotator_mode="single_call",
            annotator_provider="openai",
            openai_api_key="test-key",
        )
    )

    annotation = annotator.annotate(fake_job(), fake_extraction())

    assert annotation.result.key_entities[0].citations[0].verification_status == "unverified"
    assert annotation.result.risks[0].citations[0].verification_status == "unverified"
    assert annotation.result.risks[0].description == "Late payment interest applies."
    assert annotation.result.action_items[0].description == "Review payment terms."
    assert annotation.result.pii_detected.present is True
    assert SINGLE_CALL_CITATION_WARNING in annotation.result.warnings
    assert annotation.usage["annotator_mode"] == "single_call"
    assert annotation.usage["provider"] == "openai"


def test_anthropic_single_call_forces_citations_unverified(monkeypatch) -> None:
    from app.annotators import anthropic

    class FakeAnthropic:
        def __init__(self, api_key=None, timeout=None):
            self.messages = SimpleNamespace(create=self.create)

        def create(self, **kwargs):
            usage = SimpleNamespace(input_tokens=10, output_tokens=5)
            content = [SimpleNamespace(type="tool_use", name=anthropic.TOOL_NAME, input=rich_payload())]
            return SimpleNamespace(content=content, usage=usage)

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    annotator = anthropic.AnthropicAnnotator(
        Settings(
            _env_file=None,
            annotator_mode="single_call",
            annotator_provider="anthropic",
            anthropic_api_key="test-key",
        )
    )

    annotation = annotator.annotate(fake_job(), fake_extraction())

    assert annotation.result.key_entities[0].citations[0].verification_status == "unverified"
    assert annotation.result.risks[0].citations[0].verification_status == "unverified"
    assert annotation.result.risks[0].description == "Late payment interest applies."
    assert annotation.result.action_items[0].description == "Review payment terms."
    assert annotation.result.pii_detected.present is True
    assert SINGLE_CALL_CITATION_WARNING in annotation.result.warnings
    assert annotation.usage["annotator_mode"] == "single_call"
    assert annotation.usage["provider"] == "anthropic"


def rich_payload() -> dict:
    return {
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
        "important_dates": [],
        "action_items": [{"description": "Review payment terms."}],
        "risks": [
            {
                "description": "Late payment interest applies.",
                "severity": "medium",
                "citations": [
                    {
                        "page_number": 2,
                        "snippet": "Late payments accrue interest.",
                        "confidence": 0.75,
                        "verification_status": "revised",
                    }
                ],
            }
        ],
        "pii_detected": {"present": True, "types": ["email"], "count": 1},
    }


def fake_job():
    return SimpleNamespace(
        id=uuid4(),
        original_filename="agreement.pdf",
        detected_content_type="application/pdf",
    )


def fake_extraction() -> dict:
    return {
        "source_type": "pdf",
        "metadata": {"page_count": 1, "has_tables": False},
        "text": "Acme Corporation pays invoices within 30 days.",
        "warnings": [],
    }
