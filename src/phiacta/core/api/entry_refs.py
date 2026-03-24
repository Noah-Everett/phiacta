# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.models.entry_ref import EntryRef
from phiacta.core.repositories.entry_ref_repository import EntryRefRepository
from phiacta.core.schemas.common import PaginatedResponse
from phiacta.core.schemas.entry_ref import EntryRefCreate, EntryRefResponse

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


@router.post("", response_model=EntryRefResponse, status_code=201)
@limiter.limit("60/minute")
async def create_entry_ref(
    request: Request,
    body: EntryRefCreate,
    user: User = Depends(get_current_user),
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
    try:
        ref = await repo.create(ref)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        detail = str(exc.orig) if exc.orig else str(exc)
        if "ck_entry_refs_no_self_ref" in detail:
            raise HTTPException(
                status_code=422, detail="Self-referential entry ref not allowed",
            ) from None
        if "uq_entry_refs_from_to_rel" in detail or (
            "UNIQUE constraint failed" in detail and "entry_refs" in detail
        ):
            raise HTTPException(
                status_code=409,
                detail="Entry ref with this from/to/rel combination already exists",
            ) from None
        raise HTTPException(
            status_code=422, detail="Invalid entry reference (check entry IDs exist)",
        ) from None
    return EntryRefResponse.model_validate(ref)
