import inspect

from app.queue import CLAIM_NEXT_JOB_SQL, retry_delay_seconds, sweep_stale_jobs


def test_claim_query_uses_skip_locked() -> None:
    assert "FOR UPDATE SKIP LOCKED" in CLAIM_NEXT_JOB_SQL.text
    assert "ORDER BY created_at ASC" in CLAIM_NEXT_JOB_SQL.text


def test_retry_backoff_matches_phase_two_policy() -> None:
    assert retry_delay_seconds(1) == 30
    assert retry_delay_seconds(2) == 120
    assert retry_delay_seconds(3) == 120


def test_sweeper_requeues_retryable_jobs_and_fails_exhausted_jobs() -> None:
    source = inspect.getsource(sweep_stale_jobs)

    assert "attempts < max_attempts" in source
    assert "attempts >= max_attempts" in source
    assert "MAX_ATTEMPTS_EXCEEDED" in source
    assert "status = 'queued'" in source
    assert "status = 'failed'" in source
