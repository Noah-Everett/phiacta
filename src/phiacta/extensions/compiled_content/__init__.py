# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""compiled_content extension — stores and serves compiled entry output (PDF).

Compilation runs asynchronously via the job worker.  The ``on_ingest`` hook
submits a job; the ``CompileHandler`` tool handler picks it up.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.extensions.compiled_content.handler import CompileHandler
from phiacta.extensions.compiled_content.provider import CompiledContentProvider
from phiacta.extensions.compiled_content.router import router
from phiacta.plugin import IngestTrigger, PluginManifest, PluginType

logger = logging.getLogger(__name__)

manifest = PluginManifest(
    name="compiled_content",
    type=PluginType.EXTENSION,
    version="1.0.0",
    description="Stores and serves compiled entry output (e.g. PDF from LaTeX)",
)

entry_data_provider = CompiledContentProvider()
job_handler = CompileHandler()


async def on_ingest(
    entity_id: UUID, content: str | None, metadata: dict, db: AsyncSession,
) -> None:
    """Submit a compilation job when content changes.

    Trigger filtering (``on_ingest.triggers``) ensures this hook only runs
    on ``CONTENT_CHANGED`` and ``RECONCILIATION`` — not during initial
    provisioning or metadata-only changes.  The handler does the
    authoritative LaTeX-presence check via ``compile_entry()``.
    """
    from phiacta.core.repositories.entry_repository import EntryRepository
    from phiacta.jobs.repository import JobRepository

    entry = await EntryRepository(db).get_by_id(entity_id)
    if entry is None:
        return

    repo = JobRepository(db)

    # Per-user job queue depth limit
    from phiacta.config import get_settings as _get_settings
    active = await repo.count_active_by_user(entry.created_by)
    if active >= _get_settings().max_active_jobs_per_user:
        logger.warning(
            "Skipping compilation for entry %s — user %s has %d active jobs",
            entity_id, entry.created_by, active,
        )
        return

    # Cancel any pending compilation jobs for this entry — superseded by this
    # upload. Running jobs are left alone; the stale-SHA guard in the handler
    # skips stale writes safely. Cancelled (not failed) so the user-facing
    # job listing doesn't surface this internal preemption as an error.
    pending = await repo.list_jobs(
        entity_id=entity_id,
        job_type="compiled_content",
        status=["pending"],
        limit=10,
    )
    for old_job in pending:
        await repo.mark_cancelled(old_job.id, "superseded_by_newer_upload")
        logger.info("Cancelled superseded compilation job %s for entry %s", old_job.id, entity_id)

    from phiacta.core.services.entity_service import EntityService

    job = await repo.create(
        job_type="compiled_content",
        submitted_by=entry.created_by,
        input={"entry_id": str(entity_id)},
        entity_id=entity_id,
        timeout_seconds=480,  # clone (120) + compile (300) + buffer (60)
        max_attempts=3,
    )

    entity_svc = EntityService(db)
    await entity_svc.register_entity(
        entity_type="job",
        parent_id=entity_id,
        created_by=entry.created_by,
        id=job.id,
    )
    await entity_svc.log_activity(
        actor_id=entry.created_by,
        action="job.created",
        entity_id=job.id,
        metadata={"job_type": "compiled_content"},
    )

    logger.info("Submitted compilation job for entry %s", entity_id)


on_ingest.triggers = {IngestTrigger.CONTENT_CHANGED, IngestTrigger.RECONCILIATION}  # type: ignore[attr-defined]

__all__ = ["manifest", "router", "entry_data_provider", "job_handler", "on_ingest"]
