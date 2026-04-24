import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import check_database, get_db
from app.file_validation import UnsupportedFileTypeError, detect_content_type
from app.models import DocumentJob, JobStatus
from app.schemas import JobCreatedResponse, JobResponse, job_to_response
from app.storage import FileTooLargeError, save_upload

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_provider_config()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield


settings = get_settings()
app = FastAPI(
    title="Document Annotation Service",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    check_database()
    return {"status": "ready"}


@app.post("/documents", response_model=JobCreatedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_document_job(
    file: Annotated[UploadFile, File()],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key_form: Annotated[str | None, Form(alias="idempotency_key")] = None,
    idempotency_key_header: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JobCreatedResponse:
    active_settings = get_settings()
    idempotency_key = resolve_idempotency_key(idempotency_key_header, idempotency_key_form)
    original_filename = Path(file.filename or "upload").name
    job_id = uuid4()
    destination = upload_destination(active_settings.upload_dir, job_id, original_filename)

    try:
        stored = await save_upload(file, destination, active_settings.max_file_size_bytes)
        detected_content_type = detect_content_type(original_filename, stored.header_bytes)
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds max size of {exc.max_file_size_bytes} bytes",
        ) from exc
    except UnsupportedFileTypeError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc

    if idempotency_key:
        existing = db.scalar(
            select(DocumentJob).where(DocumentJob.idempotency_key == idempotency_key)
        )
        if existing:
            destination.unlink(missing_ok=True)
            if existing.sha256 == stored.sha256:
                return job_created_response(existing)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was already used for a different file.",
            )

    job = DocumentJob(
        id=job_id,
        status=JobStatus.queued,
        stage="queued",
        original_filename=original_filename,
        storage_path=str(destination),
        declared_content_type=file.content_type,
        detected_content_type=detected_content_type,
        file_size_bytes=stored.file_size_bytes,
        sha256=stored.sha256,
        idempotency_key=idempotency_key,
    )

    try:
        db.add(job)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        destination.unlink(missing_ok=True)
        if idempotency_key:
            existing = db.scalar(
                select(DocumentJob).where(DocumentJob.idempotency_key == idempotency_key)
            )
            if existing and existing.sha256 == stored.sha256:
                return job_created_response(existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used for a different file.",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        destination.unlink(missing_ok=True)
        logger.exception("failed to create document job")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not persist document job.",
        ) from exc

    return job_created_response(job)


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: UUID, db: Annotated[Session, Depends(get_db)]) -> JobResponse:
    job = db.get(DocumentJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job_to_response(job)


def resolve_idempotency_key(header_value: str | None, form_value: str | None) -> str | None:
    if header_value and form_value and header_value != form_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use either Idempotency-Key header or idempotency_key form field, not both.",
        )
    value = header_value or form_value
    return value.strip() if value and value.strip() else None


def upload_destination(upload_dir: Path, job_id: UUID, original_filename: str) -> Path:
    suffix = Path(original_filename).suffix.lower()
    filename = f"{job_id}{suffix}" if suffix else str(job_id)
    return upload_dir / filename


def job_created_response(job: DocumentJob) -> JobCreatedResponse:
    return JobCreatedResponse(
        job_id=job.id,
        status=job.status,
        status_url=f"/jobs/{job.id}",
    )
