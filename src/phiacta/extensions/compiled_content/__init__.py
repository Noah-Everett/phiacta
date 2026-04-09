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
from phiacta.plugin import PluginManifest, PluginType

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
    """Submit a compilation job if the entry might contain LaTeX.

    Uses a lightweight heuristic to skip obviously non-LaTeX entries.
    The handler does the authoritative check via ``compile_entry()``.
    """
    from phiacta.core.repositories.entry_repository import EntryRepository
    from phiacta.jobs.repository import JobRepository

    # Heuristic: skip if content is clearly not LaTeX
    if content is not None and "\\documentclass" not in content:
        return

    entry = await EntryRepository(db).get_by_id(entity_id)
    if entry is None:
        return

    from phiacta.core.services.entity_service import EntityService

    job = await JobRepository(db).create(
        job_type="compiled_content",
        submitted_by=entry.created_by,
        input={"entry_id": str(entity_id)},
        entry_id=entity_id,
        timeout_seconds=180,
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


__all__ = ["manifest", "router", "entry_data_provider", "job_handler", "on_ingest"]
