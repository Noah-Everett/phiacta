# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Shared ingestion logic — content reading + extension hook dispatch.

Extensions register on_ingest hooks via the plugin system.  This module
calls all hooks after reading content and metadata.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.core.services.git_service import GitService, RepoNotFoundError

logger = logging.getLogger(__name__)

_CONTENT_EXTENSIONS = [".md", ".tex", ".txt"]

# Type alias matching plugin.OnIngestHook
OnIngestHook = Callable[..., Coroutine]


async def _read_content_file(
    entry_id: UUID, git_service: GitService, ref: str,
) -> str | None:
    for ext in _CONTENT_EXTENSIONS:
        path = f".phiacta/content{ext}"
        try:
            content_bytes = await git_service.read_file(entry_id, path, ref=ref)
            return content_bytes.decode("utf-8")
        except RepoNotFoundError:
            continue
        except UnicodeDecodeError:
            logger.warning("Content file %s for entry %s is not valid UTF-8", path, entry_id)
            continue
    return None


async def _read_metadata(entry_id: UUID, db: AsyncSession) -> dict:
    """Read metadata from the metadata extension (if loaded)."""
    try:
        from phiacta.extensions.metadata.repository import MetadataRepository
        meta = await MetadataRepository(db).get_by_entry_id(entry_id)
        if meta is not None:
            return {"title": meta.title, "summary": meta.summary}
    except ImportError:
        pass
    return {}


async def ingest_entry(
    entry: Entry,
    sha: str,
    db: AsyncSession,
    git_service: GitService,
    *,
    on_ingest_hooks: list[OnIngestHook] | None = None,
) -> None:
    """Ingest an entry from git and call all registered extension hooks.

    Args:
        entry: The entry ORM object.
        sha: The git commit SHA to ingest from.
        db: Database session.
        git_service: Git service for reading files.
        on_ingest_hooks: Extension hooks to call after reading content.
            If None, falls back to hardcoded search_tsv (for backwards compat).
    """
    entry_id = entry.id

    # Read content and metadata — entry.yaml is no longer read
    content = await _read_content_file(entry_id, git_service, ref=sha)
    metadata = await _read_metadata(entry_id, db)

    # Call all registered on_ingest hooks
    hooks = on_ingest_hooks
    if hooks is None:
        try:
            from phiacta.extensions.search_tsv import on_ingest as _search_hook
            hooks = [_search_hook]
        except ImportError:
            hooks = []

    for hook in hooks:
        try:
            await hook(entry_id, content, metadata, db)
        except Exception:
            logger.warning(
                "on_ingest hook %s failed for entry %s",
                getattr(hook, "__name__", hook), entry_id, exc_info=True,
            )
