from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.annotation_schema import AnnotationResult
from app.annotators.base import AnnotationError
from app.config import Settings


class FakeCompiledGraph:
    def __init__(self, nodes):
        self.nodes = nodes

    def invoke(self, state):
        for name in ("plan", "act", "verify", "finalize"):
            state = self.nodes[name](state)
        return state


class FakeStateGraph:
    def __init__(self, state_type):
        self.nodes = {}

    def add_node(self, name, node):
        self.nodes[name] = node

    def set_entry_point(self, name):
        return None

    def add_edge(self, source, target):
        return None

    def compile(self):
        return FakeCompiledGraph(self.nodes)


class FakeOpenAI:
    last_kwargs = None

    def __init__(self, api_key=None, timeout=None):
        self.responses = SimpleNamespace(parse=self.parse)

    def parse(self, **kwargs):
        FakeOpenAI.last_kwargs = kwargs
        result = AnnotationResult(
            document_type="contract",
            summary="Agreement with payment terms.",
            key_entities=[
                {
                    "name": "Acme Corporation",
                    "type": "organization",
                    "confidence": 0.9,
                    "citations": [
                        {
                            "page_number": 1,
                            "snippet": "Acme Corporation pays invoices within 30 days.",
                            "confidence": 0.8,
                        }
                    ],
                }
            ],
            action_items=[],
            risks=[],
        )
        usage = SimpleNamespace(input_tokens=10, output_tokens=5)
        return SimpleNamespace(output_parsed=result, usage=usage)


class FakeAnthropic:
    def __init__(self, api_key=None, timeout=None):
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        result = AnnotationResult(
            document_type="contract",
            summary="Agreement with payment terms.",
            key_entities=[
                {
                    "name": "Acme Corporation",
                    "type": "organization",
                    "confidence": 0.9,
                    "citations": [
                        {
                            "page_number": 1,
                            "snippet": "Acme Corporation pays invoices within 30 days.",
                            "confidence": 0.8,
                        }
                    ],
                }
            ],
            action_items=[],
            risks=[],
        )
        usage = SimpleNamespace(input_tokens=11, output_tokens=6)
        content = [
            SimpleNamespace(
                type="tool_use",
                name=kwargs["tool_choice"]["name"],
                input=result.model_dump(mode="json"),
            )
        ]
        return SimpleNamespace(content=content, usage=usage)


def test_agent_annotator_returns_verified_schema_valid_result(monkeypatch) -> None:
    from app.annotators import agent

    monkeypatch.setattr(agent, "StateGraph", FakeStateGraph)
    monkeypatch.setattr(agent, "OpenAI", FakeOpenAI)
    FakeOpenAI.last_kwargs = None

    annotator = agent.AgentAnnotator(
        Settings(_env_file=None, annotator_mode="agent", openai_api_key="test-key")
    )
    annotation = annotator.annotate(fake_job(), fake_extraction())

    assert annotation.result.key_entities[0].citations[0].verification_status == "verified"
    assert annotation.usage["provider"] == "openai"
    assert annotation.usage["annotator_mode"] == "agent"
    assert annotation.usage["agent_tool_calls"] <= agent.MAX_AGENT_TOOL_CALLS
    assert annotation.usage["agent_verification_calls"] == 1
    assert annotation.usage["agent_context_truncated"] is False
    assert annotation.input_tokens == 10
    assert annotation.output_tokens == 5
    assert FakeOpenAI.last_kwargs is not None
    prompt_text = FakeOpenAI.last_kwargs["input"][1]["content"]
    assert "Source document context:" in prompt_text
    assert "Termination for convenience requires 60 days notice." in prompt_text


def test_agent_annotator_can_use_anthropic_provider(monkeypatch) -> None:
    from app.annotators import agent

    monkeypatch.setattr(agent, "StateGraph", FakeStateGraph)
    monkeypatch.setattr(agent, "Anthropic", FakeAnthropic)

    annotator = agent.AgentAnnotator(
        Settings(
            _env_file=None,
            annotator_mode="agent",
            annotator_provider="anthropic",
            anthropic_api_key="test-key",
        )
    )
    annotation = annotator.annotate(fake_job(), fake_extraction())

    assert annotation.result.key_entities[0].citations[0].verification_status == "verified"
    assert annotation.usage["provider"] == "anthropic"
    assert annotation.usage["annotator_mode"] == "agent"
    assert annotation.input_tokens == 11
    assert annotation.output_tokens == 6


def test_agent_timeout_path_raises(monkeypatch) -> None:
    from app.annotators import agent

    monkeypatch.setattr(agent, "StateGraph", FakeStateGraph)
    monkeypatch.setattr(agent, "OpenAI", FakeOpenAI)
    annotator = agent.AgentAnnotator(
        Settings(_env_file=None, annotator_mode="agent", openai_api_key="test-key")
    )

    with pytest.raises(AnnotationError, match="Agent run exceeded"):
        annotator._check_deadline({"deadline": 0})


def fake_job():
    return SimpleNamespace(
        id=uuid4(),
        original_filename="service_agreement.pdf",
        detected_content_type="application/pdf",
        annotation_tasks=["payment_terms"],
    )


def fake_extraction() -> dict:
    return {
        "source_type": "pdf",
        "metadata": {"page_count": 2, "has_tables": False},
        "text": (
            "Page 1\nAcme Corporation pays invoices within 30 days.\n\n"
            "Page 2\nTermination for convenience requires 60 days notice."
        ),
        "pages": [
            {
                "page_number": 1,
                "text": "Acme Corporation pays invoices within 30 days.",
            },
            {
                "page_number": 2,
                "text": "Termination for convenience requires 60 days notice.",
            },
        ],
        "sheets": [],
        "warnings": [],
    }
