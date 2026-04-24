from app.annotators.base import Annotation, AnnotationError, Annotator
from app.annotators.mock import MockAnnotator
from app.config import Settings


def create_annotator(settings: Settings) -> Annotator:
    if settings.annotator_mode == "mock":
        return MockAnnotator()
    if settings.annotator_mode == "single_call":
        if settings.annotator_provider == "openai":
            from app.annotators.openai import OpenAIAnnotator

            return OpenAIAnnotator(settings)
        if settings.annotator_provider == "anthropic":
            from app.annotators.anthropic import AnthropicAnnotator

            return AnthropicAnnotator(settings)
    if settings.annotator_mode == "agent":
        from app.annotators.agent import AgentAnnotator

        return AgentAnnotator(settings)
    raise AnnotationError(
        "UNKNOWN_WORKER_ERROR",
        f"Unsupported annotator mode/provider {settings.annotator_mode!r}/{settings.annotator_provider!r}",
    )


__all__ = [
    "Annotation",
    "AnnotationError",
    "Annotator",
    "create_annotator",
]
