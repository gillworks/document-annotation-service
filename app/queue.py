from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import DocumentJob


class DeterministicJobError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class SweepResult:
    requeued: int
    failed: int


CLAIM_NEXT_JOB_SQL = text(
    """
    WITH next_job AS (
      SELECT id
      FROM document_jobs
      WHERE status = 'queued'
        AND next_attempt_at <= now()
      ORDER BY created_at ASC
      LIMIT 1
      FOR UPDATE SKIP LOCKED
    )
    UPDATE document_jobs
    SET
      status = 'processing',
      stage = 'validating_file',
      locked_at = now(),
      locked_by = :worker_id,
      attempts = attempts + 1,
      error_code = NULL,
      error_message = NULL,
      updated_at = now()
    WHERE id IN (SELECT id FROM next_job)
    RETURNING id
    """
)


def claim_next_job(db: Session, worker_id: str) -> DocumentJob | None:
    job_id = db.execute(CLAIM_NEXT_JOB_SQL, {"worker_id": worker_id}).scalar_one_or_none()
    if job_id is None:
        db.commit()
        return None

    job = db.get(DocumentJob, job_id)
    db.commit()
    return job


def update_job_stage(db: Session, job_id: UUID, stage: str) -> None:
    db.execute(
        text(
            """
            UPDATE document_jobs
            SET stage = :stage, updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": job_id, "stage": stage},
    )
    db.commit()


def complete_job(db: Session, job_id: UUID) -> None:
    db.execute(
        text(
            """
            UPDATE document_jobs
            SET
              status = 'completed',
              stage = 'completed',
              locked_at = NULL,
              locked_by = NULL,
              completed_at = now(),
              updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": job_id},
    )
    db.commit()


def store_extraction(db: Session, job_id: UUID, extraction: dict) -> None:
    job = db.get(DocumentJob, job_id)
    if job is None:
        db.rollback()
        return

    job.extraction = extraction
    db.commit()


def fail_job(db: Session, job_id: UUID, code: str, message: str) -> None:
    db.execute(
        text(
            """
            UPDATE document_jobs
            SET
              status = 'failed',
              stage = 'failed',
              locked_at = NULL,
              locked_by = NULL,
              error_code = :code,
              error_message = :message,
              updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": job_id, "code": code, "message": message},
    )
    db.commit()


def retry_or_fail_job(db: Session, job_id: UUID, code: str, message: str) -> None:
    job = db.get(DocumentJob, job_id)
    if job is None:
        db.rollback()
        return

    if job.attempts >= job.max_attempts:
        fail_job(
            db,
            job_id,
            "MAX_ATTEMPTS_EXCEEDED",
            f"Job exceeded max attempts. Last error {code}: {message}",
        )
        return

    next_attempt_at = datetime.now(UTC) + timedelta(seconds=retry_delay_seconds(job.attempts))
    db.execute(
        text(
            """
            UPDATE document_jobs
            SET
              status = 'queued',
              stage = 'queued',
              locked_at = NULL,
              locked_by = NULL,
              next_attempt_at = :next_attempt_at,
              error_code = :code,
              error_message = :message,
              updated_at = now()
            WHERE id = :job_id
            """
        ),
        {
            "job_id": job_id,
            "next_attempt_at": next_attempt_at,
            "code": code,
            "message": message,
        },
    )
    db.commit()


def retry_delay_seconds(attempts_completed: int) -> int:
    if attempts_completed <= 1:
        return 30
    return 120


def sweep_stale_jobs(db: Session, stale_after: timedelta) -> SweepResult:
    cutoff = datetime.now(UTC) - stale_after
    requeued = db.execute(
        text(
            """
            UPDATE document_jobs
            SET
              status = 'queued',
              stage = 'queued',
              locked_at = NULL,
              locked_by = NULL,
              next_attempt_at = now(),
              updated_at = now()
            WHERE status = 'processing'
              AND locked_at < :cutoff
              AND attempts < max_attempts
            """
        ),
        {"cutoff": cutoff},
    ).rowcount

    failed = db.execute(
        text(
            """
            UPDATE document_jobs
            SET
              status = 'failed',
              stage = 'failed',
              locked_at = NULL,
              locked_by = NULL,
              error_code = 'MAX_ATTEMPTS_EXCEEDED',
              error_message = 'Job exceeded max attempts after its worker lock expired.',
              updated_at = now()
            WHERE status = 'processing'
              AND locked_at < :cutoff
              AND attempts >= max_attempts
            """
        ),
        {"cutoff": cutoff},
    ).rowcount

    db.commit()
    return SweepResult(requeued=requeued or 0, failed=failed or 0)


def validate_claimed_file(job: DocumentJob) -> None:
    storage_path = Path(job.storage_path)
    if not storage_path.exists():
        raise DeterministicJobError(
            "FILE_NOT_FOUND",
            f"Stored upload is missing at {storage_path}.",
        )

    actual_size = storage_path.stat().st_size
    if actual_size != job.file_size_bytes:
        raise DeterministicJobError(
            "UNKNOWN_WORKER_ERROR",
            f"Stored upload size mismatch: expected {job.file_size_bytes}, found {actual_size}.",
        )
