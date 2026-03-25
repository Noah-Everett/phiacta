# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Search tool repository — full-text search queries against view_search_tsv."""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.extensions.metadata.models import ExtensionMetadata
from phiacta.extensions.types.models import ExtensionType
from phiacta.views.search_tsv.models import ViewSearchTsv

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
    tsquery = _build_prefix_tsquery(q, language)
    rank = func.ts_rank(ViewSearchTsv.tsv, tsquery)
    total_window = func.count().over()

    stmt = (
        select(
            Entry.id.label("entry_id"),
            ExtensionMetadata.title,
            ExtensionMetadata.summary,
            ExtensionType.entry_type,
            rank.label("rank"),
            total_window.label("total"),
        )
        .join(Entry, Entry.id == ViewSearchTsv.entry_id)
        .outerjoin(ExtensionMetadata, ExtensionMetadata.entity_id == Entry.id)
        .outerjoin(ExtensionType, ExtensionType.entity_id == Entry.id)
        .where(
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
