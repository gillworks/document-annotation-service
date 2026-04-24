import logging
import signal
import time
from datetime import timedelta
from uuid import UUID

from app.config import get_settings
from app.db import SessionLocal
from app.queue import (
    DeterministicJobError,
    claim_next_job,
    complete_job,
    fail_job,
    retry_or_fail_job,
    sweep_stale_jobs,
    update_job_stage,
    validate_claimed_file,
)
from app.models import DocumentJob

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
running = True


def handle_shutdown(signum, frame) -> None:
    global running
    running = False


def main() -> None:
    settings = get_settings()
    settings.validate_provider_config()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info(
        "worker started",
        extra={"worker_id": settings.worker_id, "upload_dir": str(settings.upload_dir)},
    )
    next_sweep_at = 0.0

    while running:
        now = time.monotonic()
        if now >= next_sweep_at:
            run_sweeper(settings.worker_stale_after_seconds)
            next_sweep_at = now + max(settings.worker_sweep_interval_seconds, 1.0)

        try:
            job_id = claim_one(settings.worker_id)
        except Exception:
            logger.exception("failed to claim job")
            time.sleep(max(settings.worker_poll_interval_seconds, 0.1))
            continue

        if job_id is None:
            time.sleep(max(settings.worker_poll_interval_seconds, 0.1))
            continue

        process_claimed_job(job_id)

    logger.info("worker stopped")


def claim_one(worker_id: str) -> UUID | None:
    with SessionLocal() as db:
        job = claim_next_job(db, worker_id)
        if job is None:
            return None

        logger.info(
            "claimed job",
            extra={
                "job_id": str(job.id),
                "worker_id": worker_id,
                "attempt": job.attempts,
                "file_size_bytes": job.file_size_bytes,
                "file_type": job.detected_content_type,
            },
        )
        return job.id


def process_claimed_job(job_id: UUID) -> None:
    try:
        with SessionLocal() as db:
            job = db.get(DocumentJob, job_id)
            if job is None:
                logger.warning("claimed job disappeared", extra={"job_id": str(job_id)})
                return

            update_job_stage(db, job.id, "validating_file")
            validate_claimed_file(job)

        with SessionLocal() as db:
            update_job_stage(db, job_id, "storing_result")
            complete_job(db, job_id)

        logger.info("completed job", extra={"job_id": str(job_id)})
    except DeterministicJobError as exc:
        try:
            with SessionLocal() as db:
                fail_job(db, job_id, exc.code, exc.message)
            logger.warning(
                "failed job without retry",
                extra={"job_id": str(job_id), "error_code": exc.code},
            )
        except Exception:
            logger.exception("failed to persist deterministic job failure", extra={"job_id": str(job_id)})
    except Exception as exc:
        try:
            with SessionLocal() as db:
                retry_or_fail_job(db, job_id, "UNKNOWN_WORKER_ERROR", str(exc))
            logger.exception("worker error; job was scheduled for retry or failed", extra={"job_id": str(job_id)})
        except Exception:
            logger.exception("failed to persist retry decision", extra={"job_id": str(job_id)})


def run_sweeper(stale_after_seconds: float) -> None:
    try:
        with SessionLocal() as db:
            result = sweep_stale_jobs(db, timedelta(seconds=stale_after_seconds))
        if result.requeued or result.failed:
            logger.info(
                "swept stale processing jobs",
                extra={"requeued": result.requeued, "failed": result.failed},
            )
    except Exception:
        logger.exception("stale job sweeper failed")


if __name__ == "__main__":
    main()
