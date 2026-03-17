# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.api.rate_limit import limiter
from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.models.agent import Agent
from phiacta.repositories.entry_ref_repository import EntryRefRepository
from phiacta.repositories.entry_repository import EntryRepository
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.entry import (
    EntryCreate,
    EntryDetailResponse,
    EntryListItem,
    EntryResponse,
    EntryUpdate,
)
from phiacta.schemas.entry_ref import EntryRefResponse
from phiacta.services.entry_service import EntryService

router = APIRouter(prefix="/entries", tags=["entries"])

# Max refs returned in the detail endpoint's nested ref lists.
# High enough to be effectively unbounded for normal use; prevents
# pathological memory usage on entries with extreme ref counts.
_DETAIL_REFS_LIMIT = 500


@router.get("", response_model=PaginatedResponse[EntryListItem])
async def list_entries(
    layout_hint: str | None = Query(None),
    status: str = Query("active"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EntryListItem]:
    repo = EntryRepository(db)
    # "all" sentinel bypasses status filter (maps to None in repository)
    repo_status = None if status == "all" else status
    entries = await repo.list_entries(
        limit=limit,
        offset=offset,
        layout_hint=layout_hint,
        status=repo_status,
    )
    total = await repo.count_entries(
        layout_hint=layout_hint, status=repo_status,
    )
    items = [EntryListItem.model_validate(e) for e in entries]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{entry_id}", response_model=EntryDetailResponse)
async def get_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> EntryDetailResponse:
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    ref_repo = EntryRefRepository(db)
    outgoing = await ref_repo.list_by_entry(
        entry_id, direction="outgoing", limit=_DETAIL_REFS_LIMIT,
    )
    incoming = await ref_repo.list_by_entry(
        entry_id, direction="incoming", limit=_DETAIL_REFS_LIMIT,
    )

    result = EntryDetailResponse.model_validate(entry)
    result.outgoing_refs = [EntryRefResponse.model_validate(r) for r in outgoing]
    result.incoming_refs = [EntryRefResponse.model_validate(r) for r in incoming]
    return result


@router.post("", response_model=EntryResponse, status_code=201)
@limiter.limit("30/minute")
async def create_entry(
    request: Request,
    body: EntryCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    service = EntryService(db)
    entry = await service.create_entry(body, agent)
    return EntryResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=EntryResponse)
async def update_entry(
    entry_id: UUID,
    body: EntryUpdate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    if entry.created_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the entry author can update this entry",
        )

    if body.title is not None:
        entry.title = body.title
    if body.layout_hint is not None:
        entry.layout_hint = body.layout_hint
    if body.tags is not None:
        entry.tags = body.tags
    if body.summary is not None:
        entry.summary = body.summary
    if body.license is not None:
        entry.license = body.license
    if body.status is not None:
        entry.status = body.status

    await db.commit()
    await db.refresh(entry)
    return EntryResponse.model_validate(entry)


@router.get("/{entry_id}/references", response_model=list[EntryRefResponse])
async def get_entry_references(
    entry_id: UUID,
    direction: str = Query("both", pattern="^(both|incoming|outgoing)$"),
    db: AsyncSession = Depends(get_db),
) -> list[EntryRefResponse]:
    entry_repo = EntryRepository(db)
    entry = await entry_repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    ref_repo = EntryRefRepository(db)
    refs = await ref_repo.list_by_entry(entry_id, direction=direction)
    return [EntryRefResponse.model_validate(r) for r in refs]
