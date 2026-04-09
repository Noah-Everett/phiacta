# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""compiled_content extension — stores and serves compiled entry output (PDF).

Automatically compiles LaTeX entries on ingestion via the ``on_ingest`` hook.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

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


async def on_ingest(
    entity_id: UUID, content: str | None, metadata: dict, db: AsyncSession,
) -> None:
    """Compile LaTeX source on ingestion and store the PDF."""
    from phiacta.core.repositories.entry_repository import EntryRepository
    from phiacta.core.services.git_service import ForgejoGitService
    from phiacta.extensions.compiled_content.compile import compile_entry
    from phiacta.extensions.compiled_content.repository import CompiledContentRepository

    git = ForgejoGitService()

    # Quick check: does this entry have LaTeX source at all?
    from phiacta.extensions.compiled_content.compile import find_latex_source
    source_path, source_bytes = await find_latex_source(git, entity_id)
    if source_bytes is None:
        return  # Not a LaTeX entry — nothing to compile

    result = await compile_entry(entity_id, git=git)

    if not result.success or result.pdf_bytes is None:
        logger.warning(
            "LaTeX compilation failed for entry %s: %s",
            entity_id, result.log[:200],
        )
        return

    # Get HEAD SHA for cache key
    entry = await EntryRepository(db).get_by_id(entity_id)
    source_sha = entry.current_head_sha if entry else "unknown"

    await CompiledContentRepository(db).upsert(
        entry_id=entity_id,
        format="pdf",
        data=result.pdf_bytes,
        source_sha=source_sha,
    )

    logger.info(
        "LaTeX compiled on ingest for entry %s (%d bytes PDF)",
        entity_id, len(result.pdf_bytes),
    )


__all__ = ["manifest", "router", "entry_data_provider", "on_ingest"]
