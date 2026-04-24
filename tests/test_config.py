from app.config import Settings


def test_default_cors_origins_only_include_external_dev_frontends() -> None:
    settings = Settings(_env_file=None)

    assert settings.cors_origin_list == ["http://localhost:3000", "http://localhost:5173"]
    assert "http://localhost:8000" not in settings.cors_origin_list
