from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("multipart")

from app.db import get_db
from app.main import app


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


def test_upload_streams_file_and_returns_queued_job(tmp_path, monkeypatch) -> None:
    fake_db = FakeDb()
    settings = SimpleNamespace(
        upload_dir=tmp_path,
        max_file_size_bytes=1024 * 1024,
        validate_provider_config=lambda: None,
    )

    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    app.dependency_overrides[get_db] = lambda: fake_db

    try:
        with TestClient(app) as client:
            response = client.post(
                "/documents",
                files={"file": ("invoice.pdf", b"%PDF-1.4\nhello", "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "queued"
    assert payload["status_url"] == f"/jobs/{payload['job_id']}"
    assert len(fake_db.added) == 1
    assert Path(fake_db.added[0].storage_path).exists()
