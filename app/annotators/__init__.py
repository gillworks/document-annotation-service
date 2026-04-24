from app.annotators.base import Annotation, AnnotationError, Annotator
from app.annotators.mock import MockAnnotator
from app.config import Settings


def create_annotator(settings: Settings) -> Annotator:
    if settings.annotator_mode == "mock":
        return MockAnnotator()
    if settings.annotator_mode == "openai":
        from app.annotators.openai import OpenAIAnnotator

        return OpenAIAnnotator(settings)
    if settings.annotator_mode == "anthropic":
        from app.annotators.anthropic import AnthropicAnnotator

        return AnthropicAnnotator(settings)
    raise AnnotationError("UNKNOWN_WORKER_ERROR", f"Unsupported annotator mode {settings.annotator_mode!r}")


__all__ = [
    "Annotation",
    "AnnotationError",
    "Annotator",
    "create_annotator",
]
