from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.annotation_tasks import normalize_annotation_tasks
from app.models import JobStatus


PDF_BYTES = b"%PDF-1.4\nhello"


def test_normalize_annotation_tasks() -> None:
    assert normalize_annotation_tasks("risks, payment_terms, , parties ") == [
        "risks",
        "payment_terms",
        "parties",
    ]
    assert normalize_annotation_tasks(None) == []


def test_upload_streams_file_and_returns_queued_job(api_client, fake_db) -> None:
    response = api_client.post(
        "/documents",
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["status"] == "queued"
    assert payload["status_url"] == f"/jobs/{payload['job_id']}"
    assert len(fake_db.added) == 1
    assert Path(fake_db.added[0].storage_path).exists()
    assert fake_db.added[0].annotation_tasks == []


def test_upload_stores_annotation_tasks(api_client, fake_db) -> None:
    response = api_client.post(
        "/documents",
        data={"annotation_tasks": "risks, payment_terms, , parties"},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 202
    assert fake_db.added[0].annotation_tasks == ["risks", "payment_terms", "parties"]


def test_idempotency_allows_same_file_and_same_annotation_tasks(api_client, fake_db) -> None:
    existing_job_id = uuid4()
    fake_db.scalar_result = SimpleNamespace(
        id=existing_job_id,
        status=JobStatus.queued,
        sha256=sha256(PDF_BYTES).hexdigest(),
        annotation_tasks=["risks"],
    )

    response = api_client.post(
        "/documents",
        data={"annotation_tasks": "risks"},
        headers={"Idempotency-Key": "same-job"},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["job_id"] == str(existing_job_id)
    assert fake_db.added == []


def test_idempotency_rejects_same_file_with_different_annotation_tasks(api_client, fake_db) -> None:
    fake_db.scalar_result = SimpleNamespace(
        id=uuid4(),
        status=JobStatus.queued,
        sha256=sha256(PDF_BYTES).hexdigest(),
        annotation_tasks=["risks"],
    )

    response = api_client.post(
        "/documents",
        data={"annotation_tasks": "payment_terms"},
        headers={"Idempotency-Key": "same-job"},
        files={"file": ("invoice.pdf", PDF_BYTES, "application/pdf")},
    )

    assert response.status_code == 409
    assert "different file or annotation task set" in response.json()["detail"]
