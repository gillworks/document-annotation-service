from collections.abc import Generator
from types import SimpleNamespace

import pytest


class FakeDb:
    def __init__(self) -> None:
        self.added = []

    def scalar(self, statement):
        return None

    def add(self, value) -> None:
        self.added.append(value)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


@pytest.fixture
def fake_db() -> FakeDb:
    return FakeDb()


@pytest.fixture
def mock_settings(tmp_path):
    return SimpleNamespace(
        upload_dir=tmp_path,
        max_file_size_bytes=1024 * 1024,
        validate_provider_config=lambda: None,
    )


@pytest.fixture
def api_client(monkeypatch, fake_db: FakeDb, mock_settings) -> Generator:
    pytest.importorskip("multipart")

    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    monkeypatch.setattr("app.main.get_settings", lambda: mock_settings)
    app.dependency_overrides[get_db] = lambda: fake_db

    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
