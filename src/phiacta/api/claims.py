# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.extensions.dispatcher import dispatch_event
from phiacta.models.agent import Agent
from phiacta.models.claim import Claim
from phiacta.repositories.claim_repository import ClaimRepository
from phiacta.repositories.relation_repository import RelationRepository
from phiacta.schemas.claim import ClaimCreate, ClaimResponse, ClaimVerifyRequest
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
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    repo = ClaimRepository(db)

    # Store verification code in attrs if provided.
    attrs = dict(body.attrs)
    if body.verification_code is not None:
        attrs["verification_code"] = body.verification_code
        attrs["verification_runner_type"] = body.verification_runner_type
        attrs["verification_status"] = "pending"

    claim = Claim(
        lineage_id=uuid4(),
        version=1,
        content=body.content,
        claim_type=body.claim_type,
        namespace_id=body.namespace_id,
        created_by=agent.id,
        formal_content=body.formal_content,
        supersedes=body.supersedes,
        status=body.status,
        attrs=attrs,
        search_tsv=func.to_tsvector("english", body.content),
    )
    claim = await repo.create(claim)
    await db.commit()
    await dispatch_event(
        db, "claim.created", {"claim_ids": [str(claim.id)]}
    )

    # Dispatch verification event if code was provided.
    if body.verification_code is not None:
        await dispatch_event(
            db,
            "claim.verification_requested",
            {
                "claim_id": str(claim.id),
                "code": body.verification_code,
                "runner_type": body.verification_runner_type,
            },
        )

    return ClaimResponse.model_validate(claim)


@router.post("/{claim_id}/verify", response_model=ClaimResponse)
async def verify_claim(
    claim_id: UUID,
    body: ClaimVerifyRequest,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    repo = ClaimRepository(db)
    claim = await repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Store verification code in attrs.
    updated_attrs = dict(claim.attrs)
    updated_attrs["verification_code"] = body.code_content
    updated_attrs["verification_runner_type"] = body.runner_type
    updated_attrs["verification_status"] = "pending"
    claim.attrs = updated_attrs
    await db.commit()

    await dispatch_event(
        db,
        "claim.verification_requested",
        {
            "claim_id": str(claim.id),
            "code": body.code_content,
            "runner_type": body.runner_type,
        },
    )

    return ClaimResponse.model_validate(claim)


@router.get("/{claim_id}/verification")
async def get_verification_status(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = ClaimRepository(db)
    claim = await repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    attrs = claim.attrs or {}
    return {
        "claim_id": str(claim.id),
        "verification_level": attrs.get("verification_level"),
        "verification_status": attrs.get("verification_status"),
        "verification_result": attrs.get("verification_result"),
    }


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
