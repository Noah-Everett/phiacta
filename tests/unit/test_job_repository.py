# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for JobRepository — verifies the job lifecycle against a real DB.

Each test exercises the intended behavior of one lifecycle transition:
create → claim → complete/fail/retry. Uses the db_session fixture
(SQLite in-memory) so every test gets a clean database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.core.models.user import User
from phiacta.jobs.models import Job
from phiacta.jobs.repository import JobRepository
from tests.conftest import make_entry, make_user


async def _seed_user(db: AsyncSession) -> User:
    user = User(**make_user())
    db.add(user)
    await db.flush()
    return user


async def _reload(db: AsyncSession, job_id) -> Job:
    """Re-fetch from DB to see bulk update effects."""
    from sqlalchemy import select

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one()
    return job


# --- Create -----------------------------------------------------------------


class TestJobCreate:
    async def test_new_job_starts_pending_with_zero_attempts(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)

        job = await repo.create(job_type="latex", submitted_by=user.id, input={"src": "main.tex"})

        assert job.id is not None
        assert job.job_type == "latex"
        assert job.submitted_by == user.id
        assert job.status == "pending"
        assert job.attempts == 0
        assert job.input == {"src": "main.tex"}

    async def test_job_can_be_linked_to_entry(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        entry = Entry(**make_entry(created_by=user.id))
        db_session.add(entry)
        await db_session.flush()

        repo = JobRepository(db_session)
        job = await repo.create(job_type="latex", submitted_by=user.id, input={}, entry_id=entry.id)
        assert job.entry_id == entry.id

    async def test_custom_timeout_and_max_attempts(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)

        job = await repo.create(
            job_type="lean_check", submitted_by=user.id, input={},
            timeout_seconds=300, max_attempts=5,
        )
        assert job.timeout_seconds == 300
        assert job.max_attempts == 5


# --- Get --------------------------------------------------------------------


class TestJobGet:
    async def test_returns_existing_job(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})

        found = await repo.get(job.id)
        assert found is not None
        assert found.id == job.id

    async def test_returns_none_for_missing_id(self, db_session: AsyncSession) -> None:
        repo = JobRepository(db_session)
        assert await repo.get(uuid4()) is None


# --- Claim ------------------------------------------------------------------


class TestJobClaimBatch:
    async def test_claimed_job_transitions_to_running(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})
        await db_session.commit()

        claimed = await repo.claim_batch(limit=1)
        assert len(claimed) == 1
        assert claimed[0].id == job.id
        await db_session.commit()

        refreshed = await _reload(db_session, job.id)
        assert refreshed.status == "running"
        assert refreshed.started_at is not None

    async def test_job_in_backoff_is_not_claimable(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})
        job.process_after = datetime.now(UTC) + timedelta(hours=1)
        await db_session.commit()

        assert await repo.claim_batch(limit=1) == []

    async def test_running_job_is_not_claimable(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})
        job.status = "running"
        await db_session.commit()

        assert await repo.claim_batch(limit=1) == []

    async def test_limit_caps_number_of_claimed_jobs(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        for _ in range(5):
            await repo.create(job_type="test", submitted_by=user.id, input={})
        await db_session.commit()

        claimed = await repo.claim_batch(limit=2)
        assert len(claimed) == 2


# --- Complete ---------------------------------------------------------------


class TestJobMarkCompleted:
    async def test_completed_job_stores_result(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})
        await db_session.commit()

        await repo.mark_completed(job.id, {"exit_code": 0, "log": "ok"})
        await db_session.commit()

        refreshed = await _reload(db_session, job.id)
        assert refreshed.status == "completed"
        assert refreshed.result == {"exit_code": 0, "log": "ok"}
        assert refreshed.completed_at is not None


# --- Fail -------------------------------------------------------------------


class TestJobMarkFailed:
    async def test_failed_job_records_error(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})
        await db_session.commit()

        await repo.mark_failed(job.id, "compilation error")
        await db_session.commit()

        refreshed = await _reload(db_session, job.id)
        assert refreshed.status == "failed"
        assert refreshed.last_error == "compilation error"
        assert refreshed.completed_at is not None

    async def test_error_message_truncated_to_2000_chars(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})
        await db_session.commit()

        await repo.mark_failed(job.id, "x" * 5000)
        await db_session.commit()

        refreshed = await _reload(db_session, job.id)
        assert len(refreshed.last_error) <= 2000


# --- Retry ------------------------------------------------------------------


class TestJobMarkRetry:
    async def test_retryable_job_returns_to_pending_with_backoff(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})
        await db_session.commit()

        retry_at = datetime.now(UTC) + timedelta(seconds=10)
        await repo.mark_retry(job.id, "docker timeout", retry_at)
        await db_session.commit()

        refreshed = await _reload(db_session, job.id)
        assert refreshed.status == "pending"
        assert refreshed.attempts == 1
        assert refreshed.process_after is not None
        assert refreshed.last_error == "docker timeout"

    async def test_exhausted_retries_become_permanent_failure(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(
            job_type="test", submitted_by=user.id, input={}, max_attempts=2,
        )
        job.attempts = 1  # already tried once
        await db_session.commit()

        retry_at = datetime.now(UTC) + timedelta(seconds=10)
        await repo.mark_retry(job.id, "still failing", retry_at)
        await db_session.commit()

        refreshed = await _reload(db_session, job.id)
        assert refreshed.status == "failed"


# --- Crash recovery ---------------------------------------------------------


class TestJobRecoverStale:
    async def test_running_jobs_reset_to_pending_on_recovery(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)
        job = await repo.create(job_type="test", submitted_by=user.id, input={})
        job.status = "running"
        await db_session.commit()

        count = await repo.recover_stale()
        await db_session.commit()
        assert count == 1

        refreshed = await _reload(db_session, job.id)
        assert refreshed.status == "pending"

    async def test_recovery_does_not_touch_pending_or_completed(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        repo = JobRepository(db_session)

        pending = await repo.create(job_type="test", submitted_by=user.id, input={})
        completed = await repo.create(job_type="test", submitted_by=user.id, input={})
        completed.status = "completed"
        await db_session.commit()

        count = await repo.recover_stale()
        assert count == 0

        p = await _reload(db_session, pending.id)
        c = await _reload(db_session, completed.id)
        assert p.status == "pending"
        assert c.status == "completed"
