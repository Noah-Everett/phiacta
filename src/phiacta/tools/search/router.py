# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Search tool router — GET /v1/tools/search/?q=... endpoint.

Tool isolation: this router does NOT import Entry models, DB sessions
from core.db, or extension models directly. DB access goes through
core.tool_deps; query logic lives in the search_tsv search service.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.tool_deps import get_db, get_optional_user, get_providers
from phiacta.extensions.search_tsv.search_service import get_active_version, search_text
from phiacta.tools.search.schemas import SearchResponse, SearchResultItem

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_LANGUAGE = "english"

_RESERVED_PARAMS = frozenset({"q", "visibility", "limit", "offset"})


@router.get("/", response_model=SearchResponse)
async def search_entries(
    request: Request,
    q: str = Query(..., min_length=1, max_length=500),
    visibility: str = Query("public"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    """Full-text search over entries.

    Returns entries ranked by relevance to the query string.
    Uses precomputed tsvectors from the search_tsv extension.
    """
    q = q.strip()
    if not q:
        raise HTTPException(status_code=422, detail="Query must not be blank")

    providers = get_providers(request)
    filterable = {
        field: provider
        for provider in providers
        for field in provider.filterable_fields
    }
    ext_filters: dict[str, str] = {}
    for param, value in request.query_params.items():
        if param not in _RESERVED_PARAMS and param in filterable:
            ext_filters[param] = value

    version = await get_active_version(db=db)
    if version is None:
        return SearchResponse(
            items=[], total=0, limit=limit, offset=offset, version_id=None,
        )

    language = (
        version.parameters.get("language", _DEFAULT_LANGUAGE)
        if version.parameters
        else _DEFAULT_LANGUAGE
    )

    repo_visibility = None if visibility == "all" else visibility

    try:
        rows, total = await search_text(
            q=q, version_id=version.id, language=language,
            db=db, limit=limit, offset=offset,
            visibility=repo_visibility, user=user,
            filters=ext_filters if ext_filters else None,
            providers=providers if ext_filters else None,
        )
    except ProgrammingError:
        if language != _DEFAULT_LANGUAGE:
            logger.warning(
                "search failed with language=%r, retrying with '%s'",
                language, _DEFAULT_LANGUAGE,
            )
            rows, total = await search_text(
                q=q, version_id=version.id, language=_DEFAULT_LANGUAGE,
                db=db, limit=limit, offset=offset,
                visibility=repo_visibility, user=user,
                filters=ext_filters if ext_filters else None,
                providers=providers if ext_filters else None,
            )
        else:
            raise

    items = [
        SearchResultItem(
            entry_id=r.entry_id,
            rank=float(r.rank),
            title=getattr(r, "title", None),
            summary=getattr(r, "summary", None),
            entry_type=getattr(r, "entry_type", None),
        )
        for r in rows
    ]

    return SearchResponse(
        items=items, total=total, limit=limit, offset=offset,
        version_id=version.id,
    )
