import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_cors_origins_only_include_external_dev_frontends() -> None:
    settings = Settings(_env_file=None)

    assert settings.cors_origin_list == ["http://localhost:3000", "http://localhost:5173"]
    assert "http://localhost:8000" not in settings.cors_origin_list


def test_default_annotation_strategy_uses_openai_single_call() -> None:
    settings = Settings(_env_file=None)

    assert settings.annotator_mode == "single_call"
    assert settings.annotator_provider == "openai"


def test_provider_names_are_not_valid_annotator_modes() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, annotator_mode="openai")

    with pytest.raises(ValidationError):
        Settings(_env_file=None, annotator_mode="anthropic")


def test_non_mock_openai_provider_requires_openai_key() -> None:
    settings = Settings(
        _env_file=None,
        annotator_mode="agent",
        annotator_provider="openai",
        openai_api_key=None,
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is required when ANNOTATOR_PROVIDER=openai"):
        settings.validate_provider_config()


def test_non_mock_anthropic_provider_requires_anthropic_key() -> None:
    settings = Settings(
        _env_file=None,
        annotator_mode="agent",
        annotator_provider="anthropic",
        anthropic_api_key=None,
    )

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is required when ANNOTATOR_PROVIDER=anthropic"):
        settings.validate_provider_config()


def test_mock_mode_does_not_require_provider_key() -> None:
    settings = Settings(_env_file=None, annotator_mode="mock", openai_api_key=None, anthropic_api_key=None)

    settings.validate_provider_config()
