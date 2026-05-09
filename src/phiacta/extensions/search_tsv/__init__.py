# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""search_tsv extension — precomputed tsvectors for full-text search.

Computes and caches PostgreSQL tsvectors from entry content. The search
tool queries this extension data. This plugin provides the precomputed
cache and a read-only API endpoint for inspecting raw tsvector data.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.extensions.search_tsv.router import router
from phiacta.extensions.search_tsv.models import ViewSearchTsv  # noqa: F401 — ensure model registered with Base
from phiacta.extensions.search_tsv.compute import compute_search_tsv
from phiacta.plugin import PluginManifest, PluginType

manifest = PluginManifest(
    name="search_tsv",
    type=PluginType.EXTENSION,
    version="1.0.0",
    depends_on=[],
    description="Precomputed tsvectors for full-text search",
)


async def on_ingest(
    entity_id: UUID, content: str | None, metadata: dict, db: AsyncSession,
) -> None:
    """Recompute search tsvector when entry content or metadata changes."""
    parts: list[str] = []
    title = metadata.get("title")
    if title:
        parts.append(title)
    if content:
        parts.append(content)
    searchable = "\n\n".join(parts) if parts else None
    await compute_search_tsv(entity_id=entity_id, content_cache=searchable, version_id=None, db=db)


on_ingest.path_patterns = (".phiacta/content.*", ".phiacta/content/*")  # type: ignore[attr-defined]

__all__ = ["manifest", "router", "on_ingest"]
