# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Full-text search query service for the search_tsv extension.

Contains the search query logic that was previously in
tools/search/repository.py. Tools call this service instead of
building SQLAlchemy queries with Entry/extension models directly.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.compose import EntryDataProvider
from phiacta.core.models.entry import Entry
from phiacta.core.models.user import User
from phiacta.core.visibility import discovery_condition
from phiacta.extensions.search_tsv.models import ViewSearchTsv

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
    visibility: str | None = None,
    user: User | None = None,
    filters: dict[str, str] | None = None,
    providers: list[EntryDataProvider] | None = None,
) -> tuple[list[Row], bool]:
    """Full-text search with optional filtering.

    Returns (rows, has_more) instead of (rows, total).
    Uses offset-based pagination internally (rank is unstable for keyset).
    Fetches limit+1 to detect has_more.
    """
    tsquery = _build_prefix_tsquery(q, language)
    rank = func.ts_rank(ViewSearchTsv.tsv, tsquery)

    columns = [Entry.id.label("entry_id"), rank.label("rank")]
    if ExtensionMetadata is not None:
        columns.extend([ExtensionMetadata.title, ExtensionMetadata.summary])
    if ExtensionType is not None:
        columns.append(ExtensionType.entry_type)

    stmt = (
        select(*columns)
        .join(Entry, Entry.id == ViewSearchTsv.entry_id)
    )
    if ExtensionMetadata is not None:
        stmt = stmt.outerjoin(ExtensionMetadata, ExtensionMetadata.entity_id == Entry.id)
    if ExtensionType is not None:
        stmt = stmt.outerjoin(ExtensionType, ExtensionType.entity_id == Entry.id)

    where_clauses = [
        ViewSearchTsv.version_id == version_id,
        ViewSearchTsv.tsv.op("@@")(tsquery),
    ]
    if visibility is not None:
        where_clauses.append(Entry.visibility == visibility)
    where_clauses.append(discovery_condition(user))

    stmt = stmt.where(*where_clauses)

    if filters and providers:
        for field, value in filters.items():
            for provider in providers:
                if field in provider.filterable_fields:
                    stmt = provider.apply_search_filter(
                        stmt, Entry.id, field, value,
                    )
                    break

    # Fetch limit+1 to detect has_more
    stmt = stmt.order_by(rank.desc()).limit(limit + 1).offset(offset)

    result = await db.execute(stmt)
    rows = list(result.all())

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    return rows, has_more
