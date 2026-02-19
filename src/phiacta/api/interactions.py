# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.extensions.dispatcher import dispatch_event
from phiacta.models.agent import Agent
from phiacta.models.interaction import Interaction
from phiacta.repositories.claim_repository import ClaimRepository
from phiacta.repositories.interaction_repository import InteractionRepository
from phiacta.schemas.common import PaginatedResponse
from phiacta.schemas.interaction import (
    InteractionCreate,
    InteractionListResponse,
    InteractionResponse,
    InteractionUpdate,
)

limiter = Limiter(key_func=get_remote_address)

# 15-minute edit window (seconds)
_EDIT_WINDOW_SECONDS = 15 * 60

# Body-size limits per kind
_BODY_LIMIT_BY_KIND: dict[str, int] = {
    "review": 10_000,
}

# ---------------------------------------------------------------------------
# Router 1: /claims/{claim_id}/interactions (list + create)
# ---------------------------------------------------------------------------
claim_interactions_router = APIRouter(
    prefix="/claims/{claim_id}/interactions", tags=["interactions"]
)


@claim_interactions_router.get(
    "", response_model=PaginatedResponse[InteractionListResponse]
)
async def list_interactions(
    claim_id: UUID,
    kind: str | None = Query(None, pattern="^(vote|review)$"),
    signal: str | None = Query(None, pattern="^(agree|disagree|neutral)$"),
    author_id: UUID | None = Query(None),
    sort: str = Query("newest", pattern="^(newest|oldest)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[InteractionListResponse]:
    claim_repo = ClaimRepository(db)
    claim = await claim_repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    repo = InteractionRepository(db)
    interactions = await repo.list_by_claim(
        claim_id,
        kind=kind,
        signal=signal,
        author_id=author_id,
        sort=sort,
        limit=limit,
        offset=offset,
    )

    total = await repo.count_by_claim(
        claim_id, kind=kind, signal=signal, author_id=author_id,
    )
    items = [InteractionListResponse.model_validate(i) for i in interactions]
    return PaginatedResponse(
        items=items, total=total, limit=limit, offset=offset
    )


@claim_interactions_router.post(
    "", response_model=InteractionResponse, status_code=201
)
@limiter.limit("30/minute")
async def create_interaction(
    request: Request,
    claim_id: UUID,
    body: InteractionCreate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    # Validate claim exists
    claim_repo = ClaimRepository(db)
    claim = await claim_repo.get_by_id(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")

    repo = InteractionRepository(db)

    # Enforce one active signal per agent per claim.
    # Use a savepoint so a concurrent duplicate triggers IntegrityError
    # instead of silently passing the check.
    if body.signal is not None:
        existing_signal = await repo.get_signal_by_agent(claim_id, agent.id)
        if existing_signal is not None:
            raise HTTPException(
                status_code=409,
                detail="You already have an active signal on this claim. "
                "Delete your existing vote/review first.",
            )

    interaction = Interaction(
        claim_id=claim_id,
        author_id=agent.id,
        kind=body.kind,
        signal=body.signal,
        confidence=body.confidence,
        weight=1.0,
        author_trust_snapshot=agent.trust_score,
        body=body.body,
        attrs=body.attrs,
    )
    try:
        interaction = await repo.create(interaction)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="You already have an active signal on this claim. "
            "Delete your existing vote/review first.",
        )

    # Re-fetch with author loaded
    interaction = await repo.get_with_author(interaction.id)

    await dispatch_event(
        db,
        "interaction.created",
        {
            "interaction_id": str(interaction.id),
            "claim_id": str(claim_id),
            "kind": body.kind,
            "author_id": str(agent.id),
        },
    )

    return InteractionResponse.model_validate(interaction)


# ---------------------------------------------------------------------------
# Router 2: /interactions/{interaction_id} (single, patch, delete)
# ---------------------------------------------------------------------------
interactions_router = APIRouter(prefix="/interactions", tags=["interactions"])


async def _get_interaction_or_404(
    interaction_id: UUID, db: AsyncSession
) -> Interaction:
    repo = InteractionRepository(db)
    interaction = await repo.get_with_author(interaction_id)
    if interaction is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return interaction


@interactions_router.get("/{interaction_id}", response_model=InteractionResponse)
async def get_interaction(
    interaction_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    interaction = await _get_interaction_or_404(interaction_id, db)
    return InteractionResponse.model_validate(interaction)


@interactions_router.patch("/{interaction_id}", response_model=InteractionResponse)
async def update_interaction(
    interaction_id: UUID,
    body: InteractionUpdate,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    interaction = await _get_interaction_or_404(interaction_id, db)

    if interaction.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Interaction has been deleted")

    # Author-only
    if interaction.author_id != agent.id:
        raise HTTPException(
            status_code=403, detail="Only the author can edit this interaction"
        )

    # 15-minute edit window
    elapsed = (
        datetime.now(timezone.utc) - interaction.created_at.replace(tzinfo=timezone.utc)
    ).total_seconds()
    if elapsed > _EDIT_WINDOW_SECONDS:
        raise HTTPException(
            status_code=403, detail="Edit window has expired (15 minutes)"
        )

    # Reviews only (votes have no body)
    if interaction.kind != "review":
        raise HTTPException(
            status_code=422, detail="Only reviews can be edited"
        )

    kind_limit = _BODY_LIMIT_BY_KIND.get(interaction.kind, 10_000)
    if len(body.body) > kind_limit:
        raise HTTPException(
            status_code=422,
            detail=f"Body exceeds maximum length of {kind_limit}",
        )

    # Preserve original body in edit_history
    attrs = dict(interaction.attrs)
    edit_history = attrs.get("edit_history", [])
    edit_history.append(
        {
            "body": interaction.body,
            "edited_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    # Cap edit history to prevent unbounded growth
    if len(edit_history) > 50:
        edit_history = edit_history[-50:]
    attrs["edit_history"] = edit_history
    interaction.attrs = attrs
    interaction.body = body.body
    await db.flush()
    await db.commit()

    # Re-fetch
    interaction = await _get_interaction_or_404(interaction_id, db)

    await dispatch_event(
        db,
        "interaction.updated",
        {
            "interaction_id": str(interaction_id),
            "claim_id": str(interaction.claim_id),
            "author_id": str(agent.id),
        },
    )

    return InteractionResponse.model_validate(interaction)


@interactions_router.delete("/{interaction_id}", status_code=204)
async def delete_interaction(
    interaction_id: UUID,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> None:
    interaction = await _get_interaction_or_404(interaction_id, db)

    if interaction.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Interaction already deleted")

    # Author-only
    if interaction.author_id != agent.id:
        raise HTTPException(
            status_code=403, detail="Only the author can delete this interaction"
        )

    repo = InteractionRepository(db)
    await repo.soft_delete(interaction)
    await db.commit()

    await dispatch_event(
        db,
        "interaction.deleted",
        {
            "interaction_id": str(interaction_id),
            "claim_id": str(interaction.claim_id),
            "author_id": str(agent.id),
        },
    )
