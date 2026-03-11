# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.models.agent import Agent
from phiacta.models.entry_ref import EntryRef
from phiacta.repositories.entry_ref_repository import EntryRefRepository
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.entry_ref import EntryRefCreate, EntryRefResponse

limiter = Limiter(key_func=get_remote_address)

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
    elif to_entry_id is not None:
        refs = await repo.list_by_entry(
            to_entry_id, direction="incoming", limit=limit, offset=offset,
        )
    elif rel is not None:
        refs = await repo.list_by_rel(rel, limit=limit, offset=offset)
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


@router.post("", response_model=EntryRefResponse, status_code=201)
@limiter.limit("60/minute")
async def create_entry_ref(
    request: Request,
    body: EntryRefCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> EntryRefResponse:
    ref = EntryRef(
        from_entry_id=body.from_entry_id,
        to_entry_id=body.to_entry_id,
        rel=body.rel,
        version_sha=body.version_sha,
        note=body.note,
    )
    repo = EntryRefRepository(db)
    ref = await repo.create(ref)
    await db.commit()
    return EntryRefResponse.model_validate(ref)
