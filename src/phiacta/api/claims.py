# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from phiacta.db.session import get_db
from phiacta.models.claim import Claim
from phiacta.repositories.claim_repository import ClaimRepository
from phiacta.repositories.relation_repository import RelationRepository
from phiacta.schemas.claim import ClaimCreate, ClaimResponse
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.relation import RelationResponse

router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("", response_model=PaginatedResponse[ClaimResponse])
async def list_claims(
    namespace_id: UUID | None = Query(None),
    claim_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ClaimResponse]:
    repo = ClaimRepository(db)
    claims = await repo.list_claims(
        limit=limit,
        offset=offset,
        claim_type=claim_type,
        namespace_id=namespace_id,
    )
    # Apply status filter if provided (not in repo method)
    if status is not None:
        claims = [c for c in claims if c.status == status]
    items = [ClaimResponse.model_validate(c) for c in claims]
    return PaginatedResponse(items=items, total=len(items), limit=limit, offset=offset)


@router.get("/{claim_id}", response_model=ClaimResponse)
async def get_claim(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    repo = ClaimRepository(db)
    claim = await repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    return ClaimResponse.model_validate(claim)


@router.post("", response_model=ClaimResponse, status_code=201)
async def create_claim(
    body: ClaimCreate,
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    repo = ClaimRepository(db)
    claim = Claim(
        lineage_id=uuid4(),
        version=1,
        content=body.content,
        claim_type=body.claim_type,
        namespace_id=body.namespace_id,
        created_by=body.created_by,
        formal_content=body.formal_content,
        supersedes=body.supersedes,
        status=body.status,
        attrs=body.attrs,
        search_tsv=func.to_tsvector("english", body.content),
    )
    claim = await repo.create(claim)
    await db.commit()
    return ClaimResponse.model_validate(claim)


@router.get("/{claim_id}/relations", response_model=list[RelationResponse])
async def get_claim_relations(
    claim_id: UUID,
    direction: str = Query("both", pattern="^(both|incoming|outgoing)$"),
    db: AsyncSession = Depends(get_db),
) -> list[RelationResponse]:
    claim_repo = ClaimRepository(db)
    claim = await claim_repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    rel_repo = RelationRepository(db)
    relations = await rel_repo.get_relations_for_claim(claim_id, direction=direction)
    return [RelationResponse.model_validate(r) for r in relations]
