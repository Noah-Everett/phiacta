# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""search_tsv repository — encapsulates queries for the view_search_tsv table.

Does NOT inherit from BaseRepository because view operations have different
semantics: upsert (not create/update), composite PK, no updated_at column.

All functions use keyword-only arguments for clarity at call sites.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.view_version import ViewVersion
from phiacta.extensions.search_tsv.models import ViewSearchTsv

logger = logging.getLogger(__name__)


async def get_by_entry(
    *,
    entry_id: UUID,
    version_id: UUID,
    db: AsyncSession,
) -> ViewSearchTsv | None:
    """Get the tsvector row for an entry+version. Returns None if not found."""
    result = await db.execute(
        select(ViewSearchTsv).where(
            ViewSearchTsv.entry_id == entry_id,
            ViewSearchTsv.version_id == version_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert(
    *,
    entry_id: UUID,
    version_id: UUID,
    content: str,
    language: str = "english",
    db: AsyncSession,
) -> None:
    """Upsert a tsvector row using INSERT ... ON CONFLICT DO UPDATE."""
    stmt = pg_insert(ViewSearchTsv).values(
        entry_id=entry_id,
        version_id=version_id,
        tsv=func.to_tsvector(language, content),
        computed_at=func.now(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["entry_id", "version_id"],
        set_={
            "tsv": func.to_tsvector(language, content),
            "computed_at": func.now(),
        },
    )
    await db.execute(stmt)


async def delete_by_entry(
    *,
    entry_id: UUID,
    version_id: UUID,
    db: AsyncSession,
) -> None:
    """Delete the tsvector row for an entry+version. No-op if not found."""
    await db.execute(
        delete(ViewSearchTsv).where(
            ViewSearchTsv.entry_id == entry_id,
            ViewSearchTsv.version_id == version_id,
        )
    )


async def get_active_version(
    *,
    db: AsyncSession,
) -> ViewVersion | None:
    """Get the active ViewVersion for search_tsv."""
    result = await db.execute(
        select(ViewVersion)
        .where(
            ViewVersion.view_type == "search_tsv",
            ViewVersion.status == "active",
        )
        .order_by(ViewVersion.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_version_by_string(
    *,
    version: str,
    db: AsyncSession,
) -> ViewVersion | None:
    """Get a ViewVersion by its version string (e.g., 'v1')."""
    result = await db.execute(
        select(ViewVersion).where(
            ViewVersion.view_type == "search_tsv",
            ViewVersion.version == version,
        )
    )
    return result.scalar_one_or_none()
