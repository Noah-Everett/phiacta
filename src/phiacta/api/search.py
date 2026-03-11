# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db
from phiacta.models.entry import Entry
from phiacta.schemas.entry import EntryResponse
from phiacta.schemas.search import SearchRequest, SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search_entries(
    body: SearchRequest,
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    # Full-text search deferred to Phase 4 (Discovery).
    # For now, do a simple ILIKE title search as a placeholder.
    stmt = select(Entry).where(Entry.title.ilike(f"%{body.query}%"))

    if body.layout_hint is not None:
        stmt = stmt.where(Entry.layout_hint == body.layout_hint)

    stmt = stmt.limit(body.limit).offset(body.offset)

    result = await db.execute(stmt)
    entries = result.scalars().all()

    results = [
        SearchResult(
            entry=EntryResponse.model_validate(e),
            rank=1.0,
        )
        for e in entries
    ]

    return SearchResponse(results=results, total=len(results), query=body.query)
