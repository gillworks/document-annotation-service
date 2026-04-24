from typing import Any

from openai import APITimeoutError, OpenAI, RateLimitError

from app.annotation_schema import AnnotationResult
from app.annotators.base import (
    Annotation,
    AnnotationError,
    Annotator,
    build_annotation_messages,
    enforce_single_call_citation_provenance,
    validate_annotation_payload,
)
from app.config import Settings
from app.models import DocumentJob


class OpenAIAnnotator(Annotator):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds)

    def annotate(self, job: DocumentJob, extraction: dict[str, Any]) -> Annotation:
        try:
            response = self.client.responses.parse(
                model=self.settings.annotator_model,
                input=build_annotation_messages(job, extraction),
                text_format=AnnotationResult,
            )
        except APITimeoutError as exc:
            raise AnnotationError("LLM_TIMEOUT", f"OpenAI annotation timed out: {exc}") from exc
        except RateLimitError as exc:
            raise AnnotationError("LLM_RATE_LIMITED", f"OpenAI rate limit hit: {exc}") from exc
        except Exception as exc:
            raise AnnotationError("UNKNOWN_WORKER_ERROR", f"OpenAI annotation failed: {exc}") from exc

        if response.output_parsed is None:
            raise AnnotationError("LLM_SCHEMA_VALIDATION_FAILED", "OpenAI response did not include parsed output.")
        parsed = enforce_single_call_citation_provenance(
            validate_annotation_payload(response.output_parsed.model_dump(mode="json"))
        )

        usage = response_usage(response)
        return Annotation(
            result=parsed,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            usage={
                "provider": "openai",
                "annotator_mode": "single_call",
                "model": self.settings.annotator_model,
                **usage,
            },
        )


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
