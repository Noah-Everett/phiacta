# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.models.agent import Agent
from phiacta.models.review import Review
from phiacta.repositories.claim_repository import ClaimRepository
from phiacta.repositories.review_repository import ReviewRepository
from phiacta.schemas.review import ReviewCreate, ReviewResponse

router = APIRouter(prefix="/claims/{claim_id}/reviews", tags=["reviews"])


@router.get("", response_model=list[ReviewResponse])
async def list_reviews(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ReviewResponse]:
    claim_repo = ClaimRepository(db)
    claim = await claim_repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    review_repo = ReviewRepository(db)
    reviews = await review_repo.list_by_claim(claim_id)
    return [ReviewResponse.model_validate(r) for r in reviews]


@router.post("", response_model=ReviewResponse, status_code=201)
async def create_review(
    claim_id: UUID,
    body: ReviewCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    claim_repo = ClaimRepository(db)
    claim = await claim_repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    review_repo = ReviewRepository(db)
    existing = await review_repo.get_by_claim_and_reviewer(claim_id, agent.id)
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="You have already reviewed this claim"
        )

    review = Review(
        claim_id=claim_id,
        reviewer_id=agent.id,
        verdict=body.verdict,
        confidence=body.confidence,
        comment=body.comment,
    )
    review = await review_repo.create(review)
    await db.commit()

    # Refresh with the reviewer relationship loaded
    await db.refresh(review, attribute_names=["reviewer"])
    return ReviewResponse.model_validate(review)
