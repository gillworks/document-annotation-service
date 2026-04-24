from typing import Any

from anthropic import APITimeoutError, Anthropic, RateLimitError

from app.annotation_schema import AnnotationResult
from app.annotators.base import (
    Annotation,
    AnnotationError,
    Annotator,
    build_annotation_messages,
    validate_annotation_payload,
)
from app.config import Settings
from app.models import DocumentJob


TOOL_NAME = "record_document_annotation"


class AnthropicAnnotator(Annotator):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = Anthropic(api_key=settings.anthropic_api_key, timeout=settings.llm_timeout_seconds)

    def annotate(self, job: DocumentJob, extraction: dict[str, Any]) -> Annotation:
        messages = build_annotation_messages(job, extraction)
        system = messages[0]["content"]
        user = messages[1]["content"]

        try:
            response = self.client.messages.create(
                model=self.settings.annotator_model,
                max_tokens=1600,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[
                    {
                        "name": TOOL_NAME,
                        "description": "Record the structured document annotation.",
                        "input_schema": AnnotationResult.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except APITimeoutError as exc:
            raise AnnotationError("LLM_TIMEOUT", f"Anthropic annotation timed out: {exc}") from exc
        except RateLimitError as exc:
            raise AnnotationError("LLM_RATE_LIMITED", f"Anthropic rate limit hit: {exc}") from exc
        except Exception as exc:
            raise AnnotationError("UNKNOWN_WORKER_ERROR", f"Anthropic annotation failed: {exc}") from exc

        payload = first_tool_payload(response)
        result = validate_annotation_payload(payload)
        usage = response_usage(response)
        return Annotation(
            result=result,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            usage={
                "provider": "anthropic",
                "model": self.settings.annotator_model,
                **usage,
            },
        )


def first_tool_payload(response: Any) -> Any:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
            return getattr(block, "input", None)
    raise AnnotationError("LLM_SCHEMA_VALIDATION_FAILED", "Anthropic response did not call the annotation tool.")


def response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    return {
        key: value
        for key, value in {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }.items()
        if value is not None
    }
