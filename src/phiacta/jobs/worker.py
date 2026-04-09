# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Job worker: background asyncio task that polls the jobs table and
dispatches to registered tool handlers.

Modeled after the outbox worker. Uses SELECT FOR UPDATE SKIP LOCKED
for safe concurrent polling. Provides ``submit_and_wait`` for tool
routers that need to block until a job completes.

Retry policy:
    - **Infrastructure errors** (JobInfraError): retried with exponential
      backoff up to ``max_attempts``, then marked as ``failed``.
    - **User/input errors** (all other exceptions): marked as ``failed``
      immediately — no retry.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from phiacta.jobs.models import Job
from phiacta.jobs.repository import JobRepository
from phiacta.jobs.sandbox import Sandbox
from phiacta.tools.base import JobContext, JobHandler, JobInfraError

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2.0  # seconds between polls when idle
_BACKOFF_BASE = 5.0  # seconds
_BACKOFF_MAX = 300.0  # 5 minutes


def _backoff_seconds(attempts: int) -> float:
    return min(_BACKOFF_BASE * (2**attempts), _BACKOFF_MAX)


class JobWorker:
    """Processes jobs by dispatching to registered tool handlers."""

    def __init__(
        self,
        engine: AsyncEngine,
        handlers: dict[str, JobHandler],
    ) -> None:
        self._engine = engine
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self._handlers = handlers
        self._sandbox = Sandbox()
        self._running = False
        self._task: asyncio.Task[None] | None = None
        # In-process coordination: tool routers await these events
        self._waiters: dict[UUID, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the polling loop and run crash recovery."""
        # Recover jobs stuck in 'running' from a previous crash
        async with self._session_factory() as session:
            repo = JobRepository(session)
            recovered = await repo.recover_stale()
            await session.commit()
            if recovered:
                logger.warning("Recovered %d stale jobs → pending", recovered)

        # Kill orphaned Docker containers
        try:
            killed = await self._sandbox.kill_orphaned_containers()
            if killed:
                logger.warning("Killed %d orphaned containers", killed)
        except Exception:
            logger.debug("Docker not available for orphan cleanup (expected in dev)")

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info(
            "Job worker started (handlers: %s)",
            ", ".join(self._handlers) or "none",
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._sandbox.close()
        logger.info("Job worker stopped")

    # ------------------------------------------------------------------
    # Public API for tool routers
    # ------------------------------------------------------------------

    async def submit_and_wait(
        self,
        *,
        job_type: str,
        input: dict[str, Any],
        submitted_by: UUID,
        entry_id: UUID | None = None,
        timeout_seconds: int = 120,
    ) -> Job:
        """Submit a job and block until it completes or times out.

        Returns the final Job row (completed or failed).
        """
        if job_type not in self._handlers:
            raise ValueError(f"Unknown job type: {job_type!r}")

        # Insert the job
        async with self._session_factory() as session:
            repo = JobRepository(session)
            job = await repo.create(
                job_type=job_type,
                submitted_by=submitted_by,
                input=input,
                entry_id=entry_id,
                timeout_seconds=timeout_seconds,
            )
            await session.commit()
            job_id = job.id

        # Register a waiter so the poll loop can notify us
        event = asyncio.Event()
        self._waiters[job_id] = event

        try:
            # Buffer: job timeout + 30s for overhead
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds + 30)
        except asyncio.TimeoutError:
            logger.warning("submit_and_wait timed out for job %s", job_id)
        finally:
            self._waiters.pop(job_id, None)

        # Return the final state
        async with self._session_factory() as session:
            repo = JobRepository(session)
            final = await repo.get(job_id)
            if final is None:
                raise RuntimeError(f"Job {job_id} disappeared from the database")
            return final

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                processed = await self._process_batch()
                if processed == 0:
                    await asyncio.sleep(_POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Job worker error in poll loop")
                await asyncio.sleep(_POLL_INTERVAL)

    async def _process_batch(self) -> int:
        async with self._session_factory() as session:
            async with session.begin():
                repo = JobRepository(session)
                jobs = await repo.claim_batch(limit=1)

        if not jobs:
            return 0

        for job in jobs:
            await self._process_job(job)

        return len(jobs)

    async def _process_job(self, job: Job) -> None:
        handler = self._handlers.get(job.job_type)

        if handler is None:
            async with self._session_factory() as session:
                repo = JobRepository(session)
                await repo.mark_failed(job.id, f"No handler for job type: {job.job_type!r}")
                await session.commit()
            self._notify(job.id)
            return

        try:
            # Run the handler with a fresh DB session
            async with self._session_factory() as handler_session:
                ctx = JobContext(
                    db=handler_session,
                    user_id=job.submitted_by,
                    sandbox=self._sandbox,
                )
                result = await asyncio.wait_for(
                    handler.run(job.input, ctx),
                    timeout=job.timeout_seconds,
                )
                await handler_session.commit()

            # Mark completed
            async with self._session_factory() as session:
                repo = JobRepository(session)
                await repo.mark_completed(job.id, result)
                await session.commit()

            logger.info("Job %s (%s) completed", job.id, job.job_type)

        except JobInfraError as exc:
            await self._handle_retry(job, str(exc))

        except asyncio.TimeoutError:
            await self._handle_retry(job, f"Handler timed out after {job.timeout_seconds}s")

        except Exception as exc:
            # Permanent failure — no retry
            logger.exception("Job %s (%s) failed permanently", job.id, job.job_type)
            async with self._session_factory() as session:
                repo = JobRepository(session)
                await repo.mark_failed(job.id, str(exc))
                await session.commit()

        finally:
            self._notify(job.id)

    async def _handle_retry(self, job: Job, error: str) -> None:
        new_attempts = job.attempts + 1
        retry_at = datetime.now(UTC) + timedelta(seconds=_backoff_seconds(new_attempts))

        async with self._session_factory() as session:
            repo = JobRepository(session)
            await repo.mark_retry(job.id, error, retry_at)
            await session.commit()

        if new_attempts >= job.max_attempts:
            logger.error(
                "Job %s (%s) failed after %d attempts: %s",
                job.id, job.job_type, new_attempts, error[:200],
            )
        else:
            logger.warning(
                "Job %s (%s) infra error, retry %d/%d: %s",
                job.id, job.job_type, new_attempts, job.max_attempts, error[:200],
            )

    def _notify(self, job_id: UUID) -> None:
        """Wake up any ``submit_and_wait`` caller waiting on this job."""
        event = self._waiters.get(job_id)
        if event is not None:
            event.set()


async def start_job_worker(
    engine: AsyncEngine,
    handlers: dict[str, JobHandler] | None = None,
) -> JobWorker:
    """Create and start a job worker. Returns the worker for shutdown."""
    worker = JobWorker(engine, handlers or {})
    await worker.start()
    return worker
