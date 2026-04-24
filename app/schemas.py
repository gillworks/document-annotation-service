from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer

from app.models import DocumentJob, JobStatus


class JobCreatedResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    status_url: str


class ErrorInfo(BaseModel):
    code: str
    message: str


class JobResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    job_id: UUID
    status: JobStatus
    stage: str
    created_at: datetime
    updated_at: datetime
    extraction: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    error: ErrorInfo | None = None

    @model_serializer(mode="wrap")
    def omit_unrequested_extraction(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if self.extraction is None:
            data.pop("extraction", None)
        return data


def serialize_usage(job: DocumentJob) -> dict[str, Any] | None:
    usage = dict(job.usage or {})
    if job.input_tokens is not None:
        usage["input_tokens"] = job.input_tokens
    if job.output_tokens is not None:
        usage["output_tokens"] = job.output_tokens
    if job.estimated_cost_usd is not None:
        cost = job.estimated_cost_usd
        usage["estimated_cost_usd"] = float(cost) if isinstance(cost, Decimal) else cost
    return usage or None


def job_to_response(job: DocumentJob, *, include_extraction: bool = False) -> JobResponse:
    error = None
    if job.error_code or job.error_message:
        error = ErrorInfo(
            code=job.error_code or "UNKNOWN_ERROR",
            message=job.error_message or "Job failed without a detailed error message.",
        )

    return JobResponse(
        job_id=job.id,
        status=job.status,
        stage=job.stage,
        created_at=job.created_at,
        updated_at=job.updated_at,
        extraction=job.extraction if include_extraction else None,
        result=job.result,
        usage=serialize_usage(job),
        error=error,
    )
