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
from phiacta.models.reference import Reference
from phiacta.repositories.reference_repository import ReferenceRepository
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.reference import ReferenceCreate, ReferenceResponse
from phiacta.schemas.uri import PhiactaURI

limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/references", tags=["references"])


@router.get("", response_model=PaginatedResponse[ReferenceResponse])
async def list_references(
    source_uri: str | None = Query(None),
    target_uri: str | None = Query(None),
    source_claim_id: UUID | None = Query(None),
    target_claim_id: UUID | None = Query(None),
    role: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ReferenceResponse]:
    repo = ReferenceRepository(db)
    if source_uri is not None:
        references = await repo.list_by_source_uri(source_uri, limit=limit, offset=offset)
    elif target_uri is not None:
        references = await repo.list_by_target_uri(target_uri, limit=limit, offset=offset)
    elif source_claim_id is not None:
        references = await repo.list_by_claim(
            source_claim_id, direction="outgoing", limit=limit, offset=offset,
        )
    elif target_claim_id is not None:
        references = await repo.list_by_claim(
            target_claim_id, direction="incoming", limit=limit, offset=offset,
        )
    elif role is not None:
        references = await repo.list_by_role(role, limit=limit, offset=offset)
    else:
        references = await repo.list_all(limit=limit, offset=offset)
    total = await repo.count_all()
    items = [ReferenceResponse.model_validate(r) for r in references]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{reference_id}", response_model=ReferenceResponse)
async def get_reference(
    reference_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ReferenceResponse:
    repo = ReferenceRepository(db)
    reference = await repo.get_by_id(reference_id)
    if reference is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    return ReferenceResponse.model_validate(reference)


@router.post("", response_model=ReferenceResponse, status_code=201)
@limiter.limit("60/minute")
async def create_reference(
    request: Request,
    body: ReferenceCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ReferenceResponse:
    source = PhiactaURI(str(body.source_uri))
    target = PhiactaURI(str(body.target_uri))

    reference = Reference(
        source_uri=str(source),
        target_uri=str(target),
        role=body.role,
        created_by=agent.id,
        source_type=source.resource_type,
        target_type=target.resource_type,
        source_claim_id=source.claim_id,
        target_claim_id=target.claim_id,
    )
    repo = ReferenceRepository(db)
    reference = await repo.create(reference)
    await db.commit()
    return ReferenceResponse.model_validate(reference)
