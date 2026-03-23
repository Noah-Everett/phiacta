# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Search tool repository — full-text search queries against view_search_tsv.

Module-level async functions (not a class) because the search tool is
read-only with no instance state. Matches the view repository pattern.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.views.search_tsv.models import ViewSearchTsv

_SAFE_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def _build_prefix_tsquery(q: str, language: str):
    """Build a tsquery with prefix matching on the last word.

    "quantum theo" → plainto_tsquery('english', 'quantum') && to_tsquery('english', 'theo:*')
    "theo"         → to_tsquery('english', 'theo:*')

    Single words get prefix-only matching. Multiple words: all complete
    words go through plainto_tsquery (safe stemming/stop-word handling),
    last word gets a :* prefix operator so partial input matches.
    """
    words = q.split()
    if not words:
        return func.plainto_tsquery(language, q)

    # Sanitize the last word to alphanumeric only (safe for to_tsquery)
    last_raw = _SAFE_WORD_RE.findall(words[-1])
    last_safe = last_raw[0] if last_raw else ""

    if len(words) == 1:
        if not last_safe:
            return func.plainto_tsquery(language, q)
        return func.to_tsquery(language, last_safe + ":*")

    # Multiple words: complete words via plainto_tsquery, last word prefix
    complete = " ".join(words[:-1])
    complete_tsq = func.plainto_tsquery(language, complete)

    if not last_safe:
        return complete_tsq

    prefix_tsq = func.to_tsquery(language, last_safe + ":*")
    return complete_tsq.op("&&")(prefix_tsq)


async def search_text(
    *,
    q: str,
    version_id: UUID,
    language: str,
    db: AsyncSession,
    limit: int,
    offset: int,
) -> tuple[list[Row], int]:
    """Full-text search with prefix matching on the last word.

    Splits the query into words. Complete words use plainto_tsquery for
    safe parsing; the last word gets a :* prefix operator so "theo"
    matches "theorem". Uses count(*) OVER() window function to get
    results and total in one round-trip.

    Returns (rows, total) where each Row has named fields:
    entry_id, title, summary, layout_hint, rank.
    """
    tsquery = _build_prefix_tsquery(q, language)
    rank = func.ts_rank(ViewSearchTsv.tsv, tsquery)
    total_window = func.count().over()

    stmt = (
        select(
            Entry.id.label("entry_id"),
            Entry.title,
            Entry.summary,
            Entry.layout_hint,
            rank.label("rank"),
            total_window.label("total"),
        )
        .join(Entry, Entry.id == ViewSearchTsv.entry_id)
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
        total = rows[0].total
        return rows, total

    # Window function returns nothing when offset exceeds total.
    # Fall back to a count-only query.
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
    total = count_result.scalar_one()
    return [], total
