# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""search_tsv view — precomputed tsvectors for full-text search.

First view plugin in the Phiacta platform. Computes and caches PostgreSQL
tsvectors from entries.content_cache. The search tool (NEV-133) queries this
view data. This plugin provides the precomputed cache and a read-only API
endpoint for inspecting raw tsvector data.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.views.search_tsv.router import router
from phiacta.views.search_tsv.models import ViewSearchTsv  # noqa: F401 — ensure model registered with Base
from phiacta.views.search_tsv.compute import compute_search_tsv
from phiacta.plugin import PluginManifest, PluginType

manifest = PluginManifest(
    name="search_tsv",
    type=PluginType.VIEW,
    version="1.0.0",
    depends_on=[],
    description="Precomputed tsvectors for full-text search",
)


async def on_ingest(
    entry_id: UUID, content: str | None, metadata: dict, db: AsyncSession,
) -> None:
    """Recompute search tsvector when entry content or metadata changes."""
    parts: list[str] = []
    title = metadata.get("title")
    if title:
        parts.append(title)
    if content:
        parts.append(content)
    searchable = "\n\n".join(parts) if parts else None
    await compute_search_tsv(entry_id=entry_id, content_cache=searchable, version_id=None, db=db)


__all__ = ["manifest", "router", "on_ingest"]
