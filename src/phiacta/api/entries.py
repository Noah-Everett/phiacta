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
from phiacta.models.entry import Entry
from phiacta.models.outbox import Outbox
from phiacta.repositories.entry_ref_repository import EntryRefRepository
from phiacta.repositories.entry_repository import EntryRepository
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.entry import EntryCreate, EntryResponse, EntryUpdate
from phiacta.schemas.entry_ref import EntryRefResponse

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("", response_model=PaginatedResponse[EntryResponse])
async def list_entries(
    layout_hint: str | None = Query(None),
    tag: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EntryResponse]:
    repo = EntryRepository(db)
    entries = await repo.list_entries(
        limit=limit,
        offset=offset,
        layout_hint=layout_hint,
        tag=tag,
        status=status,
    )
    total = await repo.count_entries(
        layout_hint=layout_hint, tag=tag, status=status,
    )
    items = [EntryResponse.model_validate(e) for e in entries]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{entry_id}", response_model=EntryResponse)
async def get_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return EntryResponse.model_validate(entry)


@router.post("", response_model=EntryResponse, status_code=201)
@limiter.limit("30/minute")
async def create_entry(
    request: Request,
    body: EntryCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    repo = EntryRepository(db)

    entry = Entry(
        title=body.title,
        content_format=body.content_format,
        layout_hint=body.layout_hint,
        tags=body.tags,
        summary=body.summary,
        license=body.license,
        repo_name=str(agent.handle),
        created_by=agent.id,
    )
    entry = await repo.create(entry)

    # Enqueue Forgejo repo creation via outbox
    outbox_entry = Outbox(
        aggregate_id=entry.id,
        aggregate_type="entry",
        operation="create_repo",
        payload={
            "entry_id": str(entry.id),
            "title": body.title,
            "content_format": body.content_format,
            "author_id": str(agent.id),
            "author_handle": agent.handle,
        },
    )
    db.add(outbox_entry)

    await db.commit()

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
