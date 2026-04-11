# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Job repository — data access for the jobs table."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func as sa_func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.pagination import keyset_condition

from phiacta.jobs.models import Job

logger = logging.getLogger(__name__)


class JobRepository:
    """Persistence layer for jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        job_type: str,
        submitted_by: UUID,
        input: dict[str, Any],
        entity_id: UUID | None = None,
        timeout_seconds: int = 120,
        max_attempts: int = 3,
    ) -> Job:
        """Insert a new pending job and return it (flushed, not committed)."""
        job = Job(
            job_type=job_type,
            submitted_by=submitted_by,
            entity_id=entity_id,
            input=input,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def get(self, job_id: UUID) -> Job | None:
        return await self._session.get(Job, job_id)

    async def count_active_by_user(self, user_id: UUID) -> int:
        """Count pending + running jobs for a user."""
        stmt = (
            select(sa_func.count())
            .select_from(Job)
            .where(Job.submitted_by == user_id, Job.status.in_(["pending", "running"]))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def claim_batch(
        self, limit: int = 1, job_types: list[str] | None = None,
    ) -> list[Job]:
        """Claim up to ``limit`` pending jobs atomically.

        Uses SELECT FOR UPDATE SKIP LOCKED so multiple workers can
        run concurrently without processing the same job.

        If ``job_types`` is provided, only jobs matching those types are
        claimed.  This allows dedicated worker containers to handle
        specific job types.
        """
        now = datetime.now(UTC)
        stmt = (
            select(Job)
            .where(
                Job.status == "pending",
                (Job.process_after <= now) | (Job.process_after.is_(None)),
            )
            .order_by(Job.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        if job_types is not None:
            stmt = stmt.where(Job.job_type.in_(job_types))
        result = await self._session.execute(stmt)
        jobs = list(result.scalars().all())

        if jobs:
            job_ids = [j.id for j in jobs]
            await self._session.execute(
                update(Job)
                .where(Job.id.in_(job_ids))
                .values(status="running", claimed_at=now, started_at=now, updated_at=now)
            )

        return jobs

    async def mark_completed(self, job_id: UUID, result: dict[str, Any]) -> None:
        now = datetime.now(UTC)
        await self._session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="completed",
                result=result,
                completed_at=now,
                updated_at=now,
            )
        )

    async def mark_failed(
        self, job_id: UUID, error: str, *, increment_attempts: bool = True,
    ) -> None:
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "status": "failed",
            "last_error": error[:2000],
            "completed_at": now,
            "updated_at": now,
        }
        if increment_attempts:
            # Use a subquery to increment
            job = await self.get(job_id)
            if job:
                values["attempts"] = job.attempts + 1
        await self._session.execute(
            update(Job).where(Job.id == job_id).values(**values)
        )

    async def mark_retry(
        self, job_id: UUID, error: str, retry_after: datetime,
    ) -> None:
        """Return a job to pending with backoff."""
        job = await self.get(job_id)
        if job is None:
            return
        new_attempts = job.attempts + 1
        # If we've exhausted retries, fail permanently
        if new_attempts >= job.max_attempts:
            await self.mark_failed(job_id, error, increment_attempts=False)
            await self._session.execute(
                update(Job).where(Job.id == job_id).values(attempts=new_attempts)
            )
            return

        await self._session.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="pending",
                attempts=new_attempts,
                last_error=error[:2000],
                process_after=retry_after,
                updated_at=datetime.now(UTC),
            )
        )

    async def list_jobs(
        self,
        *,
        limit: int = 50,
        submitted_by: UUID | None = None,
        status: list[str] | None = None,
        job_type: str | None = None,
        entity_id: UUID | None = None,
        cursor_created_at: str | None = None,
        cursor_id: UUID | None = None,
    ) -> list[Job]:
        """List jobs with optional filters, newest first (created_at DESC)."""
        from datetime import timezone

        stmt = (
            select(Job)
            .order_by(Job.created_at.desc(), Job.id.desc())
        )
        if submitted_by is not None:
            stmt = stmt.where(Job.submitted_by == submitted_by)
        if status is not None:
            stmt = stmt.where(Job.status.in_(status))
        if job_type is not None:
            stmt = stmt.where(Job.job_type == job_type)
        if entity_id is not None:
            stmt = stmt.where(Job.entity_id == entity_id)
        if cursor_created_at is not None and cursor_id is not None:
            cursor_dt = datetime.fromisoformat(cursor_created_at).replace(tzinfo=timezone.utc)
            stmt = stmt.where(
                keyset_condition(Job.created_at, Job.id, cursor_dt, cursor_id, descending=True)
            )
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def recover_stale(self) -> int:
        """Reset jobs stuck in 'running' from a previous crash. Returns count.

        Increments ``attempts`` so that jobs which repeatedly crash the
        worker eventually hit ``max_attempts`` and fail permanently.
        """
        now = datetime.now(UTC)

        # Fail jobs that have exhausted their attempts
        failed = await self._session.execute(
            update(Job)
            .where(Job.status == "running", Job.attempts + 1 >= Job.max_attempts)
            .values(
                status="failed",
                attempts=Job.attempts + 1,
                last_error="Worker crashed — max attempts exceeded",
                completed_at=now,
                updated_at=now,
            )
            .returning(Job.id)
        )
        failed_count = len(failed.all())

        # Return remaining running jobs to pending with incremented attempts
        retried = await self._session.execute(
            update(Job)
            .where(Job.status == "running")
            .values(
                status="pending",
                attempts=Job.attempts + 1,
                process_after=None,
                updated_at=now,
            )
            .returning(Job.id)
        )
        retried_count = len(retried.all())

        return failed_count + retried_count
