from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.models import JobStatus
from app.schemas import job_to_response


def make_completed_job():
    return SimpleNamespace(
        id=uuid4(),
        status=JobStatus.completed,
        stage="completed",
        created_at=datetime(2026, 4, 24, tzinfo=UTC),
        updated_at=datetime(2026, 4, 24, tzinfo=UTC),
        extraction={"schema_version": "extraction.v1", "text": "full extracted text"},
        result={"schema_version": "1", "document_type": "invoice"},
        usage={"provider": "mock"},
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=0,
        error_code=None,
        error_message=None,
    )


def test_job_response_omits_extraction_by_default() -> None:
    payload = job_to_response(make_completed_job()).model_dump(mode="json")

    assert "extraction" not in payload
    assert payload["result"] == {"schema_version": "1", "document_type": "invoice"}
    assert payload["usage"]["provider"] == "mock"


def test_job_response_can_include_extraction_for_debugging() -> None:
    payload = job_to_response(make_completed_job(), include_extraction=True).model_dump(mode="json")

    assert payload["extraction"] == {
        "schema_version": "extraction.v1",
        "text": "full extracted text",
    }
