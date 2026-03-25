# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Search tool repository — full-text search queries against view_search_tsv."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.views.search_tsv.models import ViewSearchTsv

try:
    from phiacta.extensions.metadata.models import ExtensionMetadata
except ImportError:
    ExtensionMetadata = None  # type: ignore[assignment,misc]

try:
    from phiacta.extensions.types.models import ExtensionType
except ImportError:
    ExtensionType = None  # type: ignore[assignment,misc]

_SAFE_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def _build_prefix_tsquery(q: str, language: str):
    words = q.split()
    if not words:
        return func.plainto_tsquery(language, q)
    last_raw = _SAFE_WORD_RE.findall(words[-1])
    last_safe = last_raw[0] if last_raw else ""
    if len(words) == 1:
        if not last_safe:
            return func.plainto_tsquery(language, q)
        return func.to_tsquery(language, last_safe + ":*")
    complete = " ".join(words[:-1])
    complete_tsq = func.plainto_tsquery(language, complete)
    if not last_safe:
        return complete_tsq
    prefix_tsq = func.to_tsquery(language, last_safe + ":*")
    return complete_tsq.op("&&")(prefix_tsq)


async def search_text(
    *, q: str, version_id: UUID, language: str, db: AsyncSession,
    limit: int, offset: int,
) -> tuple[list[Row], int]:
    """Full-text search. Outerjoins metadata/types for optional enrichment."""
    tsquery = _build_prefix_tsquery(q, language)
    rank = func.ts_rank(ViewSearchTsv.tsv, tsquery)
    total_window = func.count().over()

    # Build select columns — metadata/type fields included if extensions loaded
    columns = [Entry.id.label("entry_id"), rank.label("rank")]
    if ExtensionMetadata is not None:
        columns.extend([ExtensionMetadata.title, ExtensionMetadata.summary])
    if ExtensionType is not None:
        columns.append(ExtensionType.entry_type)
    columns.append(total_window.label("total"))

    stmt = (
        select(*columns)
        .join(Entry, Entry.id == ViewSearchTsv.entry_id)
    )
    if ExtensionMetadata is not None:
        stmt = stmt.outerjoin(ExtensionMetadata, ExtensionMetadata.entity_id == Entry.id)
    if ExtensionType is not None:
        stmt = stmt.outerjoin(ExtensionType, ExtensionType.entity_id == Entry.id)

    stmt = (
        stmt.where(
            ViewSearchTsv.version_id == version_id,
            ViewSearchTsv.tsv.op("@@")(tsquery),
            Entry.status == "active",
        )
        .order_by(rank.desc())
        .limit(limit)
        .offset(offset)
    )

    result = await db.execute(stmt)
    rows = result.all()
    if rows:
        return rows, rows[0].total

    count_stmt = (
        select(func.count())
        .select_from(ViewSearchTsv)
        .join(Entry, Entry.id == ViewSearchTsv.entry_id)
        .where(
            ViewSearchTsv.version_id == version_id,
            ViewSearchTsv.tsv.op("@@")(tsquery),
            Entry.status == "active",
        )
    )
    count_result = await db.execute(count_stmt)
    return [], count_result.scalar_one()
