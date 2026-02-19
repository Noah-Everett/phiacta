# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.models.agent import Agent
from phiacta.models.source import Source
from phiacta.repositories.source_repository import SourceRepository
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.source import SourceCreate, SourceResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=PaginatedResponse[SourceResponse])
async def list_sources(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[SourceResponse]:
    repo = SourceRepository(db)
    total = await repo.count_all()
    sources = await repo.list_all(limit=limit, offset=offset)
    items = [SourceResponse.model_validate(s) for s in sources]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(
    body: SourceCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> SourceResponse:
    repo = SourceRepository(db)
    source = Source(
        source_type=body.source_type,
        submitted_by=agent.id,
        title=body.title,
        external_ref=body.external_ref,
        content_hash=body.content_hash,
        attrs=body.attrs,
    )
    source = await repo.create(source)
    await db.commit()
    return SourceResponse.model_validate(source)
