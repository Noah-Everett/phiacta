# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Search tool router — GET /v1/tools/search/?q=... endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.db.session import get_db
from phiacta.tools.search.repository import search_text
from phiacta.tools.search.schemas import SearchResponse, SearchResultItem
from phiacta.views.search_tsv.repository import get_active_version

logger = logging.getLogger(__name__)

router = APIRouter()

# Must match search_tsv compute default
_DEFAULT_LANGUAGE = "english"


@router.get("/", response_model=SearchResponse)
async def search_entries(
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Full-text search over entries. Public read — no auth required.

    Returns entries ranked by relevance to the query string.
    Uses precomputed tsvectors from the search_tsv view.
    """
    # Strip whitespace and reject blank queries
    q = q.strip()
    if not q:
        raise HTTPException(status_code=422, detail="Query must not be blank")

    # Resolve active search_tsv version
    version = await get_active_version(db=db)
    if version is None:
        return SearchResponse(
            items=[],
            total=0,
            limit=limit,
            offset=offset,
            version_id=None,
        )

    # Read language from version parameters, fallback to default
    language = (
        version.parameters.get("language", _DEFAULT_LANGUAGE)
        if version.parameters
        else _DEFAULT_LANGUAGE
    )

    # Execute search with language fallback on invalid regconfig
    try:
        rows, total = await search_text(
            q=q,
            version_id=version.id,
            language=language,
            db=db,
            limit=limit,
            offset=offset,
        )
    except ProgrammingError:
        if language != _DEFAULT_LANGUAGE:
            logger.warning(
                "search failed with language=%r, retrying with '%s'",
                language,
                _DEFAULT_LANGUAGE,
            )
            rows, total = await search_text(
                q=q,
                version_id=version.id,
                language=_DEFAULT_LANGUAGE,
                db=db,
                limit=limit,
                offset=offset,
            )
        else:
            raise

    items = [
        SearchResultItem(
            entry_id=r.entry_id,
            title=r.title,
            summary=r.summary,
            entry_type=r.entry_type,
            rank=float(r.rank),
        )
        for r in rows
    ]

    return SearchResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        version_id=version.id,
    )
