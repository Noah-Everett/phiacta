# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Cross-process job submission with DB polling.

Unlike the old in-memory ``asyncio.Event`` approach, this polls the
database for completion — so the submitter (backend API) and executor
(worker container) can live in different processes.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from phiacta.jobs.models import Job
from phiacta.jobs.repository import JobRepository

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.5  # seconds between DB polls


async def submit_and_wait(
    engine: AsyncEngine,
    *,
    job_type: str,
    input: dict[str, Any],
    submitted_by: UUID,
    entry_id: UUID | None = None,
    timeout_seconds: int = 120,
    poll_interval: float = _POLL_INTERVAL,
) -> Job:
    """Submit a job and poll the DB until it completes or times out.

    Works cross-process: the job is picked up by whatever worker container
    claims it. This function only inserts the row and polls for a terminal
    status.

    Returns the final ``Job`` row in any terminal state (completed/failed),
    or in its current state if the wait times out.
    """
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # Insert the job
    async with factory() as session:
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

    # Poll until terminal state or timeout
    # Buffer: job timeout + 30s for scheduling/execution overhead
    deadline = asyncio.get_event_loop().time() + timeout_seconds + 30

    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(poll_interval)
        async with factory() as session:
            repo = JobRepository(session)
            job = await repo.get(job_id)
            if job is None:
                raise RuntimeError(f"Job {job_id} disappeared from the database")
            if job.status in ("completed", "failed"):
                return job

    # Timed out — return whatever state we have
    logger.warning("submit_and_wait timed out for job %s", job_id)
    async with factory() as session:
        repo = JobRepository(session)
        final = await repo.get(job_id)
        if final is None:
            raise RuntimeError(f"Job {job_id} disappeared from the database")
        return final
