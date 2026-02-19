# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from slowapi import Limiter
from slowapi.util import get_remote_address

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.extensions.dispatcher import dispatch_event
from phiacta.models.agent import Agent
from phiacta.models.claim import Claim
from phiacta.models.outbox import Outbox
from phiacta.models.reference import Reference
from phiacta.repositories.claim_repository import ClaimRepository
from phiacta.repositories.reference_repository import ReferenceRepository
from phiacta.schemas.claim import ClaimCreate, ClaimResponse, ClaimUpdate
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.reference import ReferenceResponse
from phiacta.schemas.uri import PhiactaURI

limiter = Limiter(key_func=get_remote_address)

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
        status=status,
    )
    total = await repo.count_claims(
        claim_type=claim_type, namespace_id=namespace_id, status=status,
    )
    items = [ClaimResponse.model_validate(c) for c in claims]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


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
@limiter.limit("30/minute")
async def create_claim(
    request: Request,
    body: ClaimCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    repo = ClaimRepository(db)

    claim = Claim(
        title=body.title,
        claim_type=body.claim_type,
        format=body.format,
        content_cache=body.content,
        namespace_id=body.namespace_id,
        created_by=agent.id,
        status=body.status,
        attrs=body.attrs,
        search_tsv=func.to_tsvector("english", body.content),
    )
    claim = await repo.create(claim)

    # Enqueue Forgejo repo creation via outbox
    outbox_entry = Outbox(
        operation="create_repo",
        payload={
            "claim_id": str(claim.id),
            "title": body.title,
            "content": body.content,
            "format": body.format,
            "author_id": str(agent.id),
            "author_name": agent.name,
        },
    )
    db.add(outbox_entry)

    await db.commit()
    await dispatch_event(
        db, "claim.created", {"claim_ids": [str(claim.id)]}
    )

    return ClaimResponse.model_validate(claim)


@router.patch("/{claim_id}", response_model=ClaimResponse)
async def update_claim(
    claim_id: UUID,
    body: ClaimUpdate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    repo = ClaimRepository(db)
    claim = await repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    if claim.created_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the claim author can update this claim",
        )

    if body.title is not None:
        claim.title = body.title
    if body.status is not None:
        claim.status = body.status
    if body.attrs is not None:
        claim.attrs = body.attrs
    if body.content is not None:
        claim.content_cache = body.content
        claim.search_tsv = func.to_tsvector("english", body.content)
        # Enqueue content update to Forgejo
        outbox_entry = Outbox(
            operation="commit_files",
            payload={
                "claim_id": str(claim.id),
                "content": body.content,
                "format": body.format or claim.format,
                "author_id": str(agent.id),
                "author_name": agent.name,
                "message": f"Update claim content",
            },
        )
        db.add(outbox_entry)
    if body.format is not None:
        claim.format = body.format

    await db.commit()
    return ClaimResponse.model_validate(claim)


@router.post("/{claim_id}/derive", response_model=ClaimResponse, status_code=201)
@limiter.limit("10/minute")
async def derive_claim(
    request: Request,
    claim_id: UUID,
    body: ClaimCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ClaimResponse:
    """Create a new claim derived from an existing one.

    Creates a ``derives_from`` reference linking the new claim back to the
    original.
    """
    repo = ClaimRepository(db)
    original = await repo.get_by_id(claim_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    new_claim = Claim(
        title=body.title,
        claim_type=body.claim_type,
        format=body.format,
        content_cache=body.content,
        namespace_id=body.namespace_id,
        created_by=agent.id,
        status="active",
        attrs=body.attrs,
        search_tsv=func.to_tsvector("english", body.content),
    )
    new_claim = await repo.create(new_claim)

    # Enqueue Forgejo repo creation
    outbox_entry = Outbox(
        operation="create_repo",
        payload={
            "claim_id": str(new_claim.id),
            "title": body.title,
            "content": body.content,
            "format": body.format,
            "author_id": str(agent.id),
            "author_name": agent.name,
        },
    )
    db.add(outbox_entry)

    # Create derives_from reference
    source_uri = PhiactaURI(f"claim:{new_claim.id}")
    target_uri = PhiactaURI(f"claim:{original.id}")
    reference = Reference(
        source_uri=str(source_uri),
        target_uri=str(target_uri),
        role="derives_from",
        created_by=agent.id,
        source_type=source_uri.resource_type,
        target_type=target_uri.resource_type,
        source_claim_id=new_claim.id,
        target_claim_id=original.id,
    )
    db.add(reference)

    await db.commit()

    await dispatch_event(
        db,
        "claim.derived",
        {
            "claim_id": str(new_claim.id),
            "derived_from_id": str(original.id),
        },
    )

    return ClaimResponse.model_validate(new_claim)


@router.get("/{claim_id}/references", response_model=list[ReferenceResponse])
async def get_claim_references(
    claim_id: UUID,
    direction: str = Query("both", pattern="^(both|incoming|outgoing)$"),
    db: AsyncSession = Depends(get_db),
) -> list[ReferenceResponse]:
    claim_repo = ClaimRepository(db)
    claim = await claim_repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    ref_repo = ReferenceRepository(db)
    references = await ref_repo.list_by_claim(claim_id, direction=direction)
    return [ReferenceResponse.model_validate(r) for r in references]
