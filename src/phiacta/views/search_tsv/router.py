# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""search_tsv view API router.

Endpoints:
- GET /version       Active version metadata (public)
- GET /{entry_id}    Raw tsvector for an entry (public)

IMPORTANT: /version is registered BEFORE /{entry_id} to avoid route
collision — FastAPI matches routes in registration order, and "version"
would otherwise be parsed as a UUID path parameter.

The router is mounted at /v1/views/search_tsv/ by the plugin framework.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.db.session import get_db
from phiacta.views.search_tsv.repository import (
    get_active_version,
    get_by_entry,
    get_version_by_string,
)
from phiacta.views.search_tsv.schemas import (
    SearchTsvResponse,
    SearchTsvVersionResponse,
)

router = APIRouter()


@router.get("/version", response_model=SearchTsvVersionResponse)
async def get_version(
    db: AsyncSession = Depends(get_db),
) -> SearchTsvVersionResponse:
    """Return the active version metadata for the search_tsv view.

    Public read — no auth required.
    """
    version = await get_active_version(db=db)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail="No active search_tsv version found",
        )
    return SearchTsvVersionResponse.model_validate(version)


@router.get("/{entry_id}", response_model=SearchTsvResponse)
async def get_tsvector(
    entry_id: UUID,
    version: str | None = Query(None, description="Version string (default: active)"),
    db: AsyncSession = Depends(get_db),
) -> SearchTsvResponse:
    """Return the raw tsvector for an entry.

    Public read — no auth required. Enables external tool developers
    to inspect precomputed search data.
    """
    if version is not None:
        vv = await get_version_by_string(version=version, db=db)
        if vv is None:
            raise HTTPException(
                status_code=404,
                detail=f"search_tsv version '{version}' not found",
            )
        version_id = vv.id
    else:
        active = await get_active_version(db=db)
        if active is None:
            raise HTTPException(
                status_code=404,
                detail="No active search_tsv version found",
            )
        version_id = active.id

    row = await get_by_entry(
        entry_id=entry_id,
        version_id=version_id,
        db=db,
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No tsvector found for this entry",
        )

    return SearchTsvResponse(
        entry_id=row.entry_id,
        version_id=row.version_id,
        tsv=str(row.tsv),
        computed_at=row.computed_at,
    )
