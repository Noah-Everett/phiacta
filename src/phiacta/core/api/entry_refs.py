# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry refs API — read-only endpoints.

Entry refs are git-derived (from .phiacta/refs.yaml) and populated
exclusively by the ingestion pipeline. There is no POST endpoint;
to create a ref, write to refs.yaml via the file API and push.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.db.session import get_db
from phiacta.core.repositories.entry_ref_repository import EntryRefRepository
from phiacta.core.schemas.common import PaginatedResponse
from phiacta.core.schemas.entry_ref import EntryRefResponse

router = APIRouter(prefix="/entry-refs", tags=["entry-refs"])


@router.get("", response_model=PaginatedResponse[EntryRefResponse])
async def list_entry_refs(
    from_entry_id: UUID | None = Query(None),
    to_entry_id: UUID | None = Query(None),
    rel: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EntryRefResponse]:
    repo = EntryRefRepository(db)
    if from_entry_id is not None:
        refs = await repo.list_by_entry(
            from_entry_id, direction="outgoing", limit=limit, offset=offset,
        )
        total = await repo.count_by_entry(from_entry_id, direction="outgoing")
    elif to_entry_id is not None:
        refs = await repo.list_by_entry(
            to_entry_id, direction="incoming", limit=limit, offset=offset,
        )
        total = await repo.count_by_entry(to_entry_id, direction="incoming")
    elif rel is not None:
        refs = await repo.list_by_rel(rel, limit=limit, offset=offset)
        total = await repo.count_by_rel(rel)
    else:
        refs = await repo.list_all(limit=limit, offset=offset)
        total = await repo.count_all()
    items = [EntryRefResponse.model_validate(r) for r in refs]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{entry_ref_id}", response_model=EntryRefResponse)
async def get_entry_ref(
    entry_ref_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> EntryRefResponse:
    repo = EntryRefRepository(db)
    ref = await repo.get_by_id(entry_ref_id)
    if ref is None:
        raise HTTPException(status_code=404, detail="Entry ref not found")
    return EntryRefResponse.model_validate(ref)
