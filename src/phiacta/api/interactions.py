# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from phiacta.auth.dependencies import get_current_agent
from phiacta.db.session import get_db
from phiacta.extensions.dispatcher import dispatch_event
from phiacta.models.agent import Agent
from phiacta.models.claim import Claim
from phiacta.models.interaction import Interaction, InteractionReference
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

# ---------------------------------------------------------------------------
# Body-size limits per kind (enforced on PATCH -- the original kind's limit).
# ---------------------------------------------------------------------------
_BODY_LIMIT_BY_KIND: dict[str, int] = {
    "comment": 10_000,
    "review": 10_000,
    "issue": 10_000,
    "suggestion": 50_000,
}

# ---------------------------------------------------------------------------
# 15-minute edit window (seconds)
# ---------------------------------------------------------------------------
_EDIT_WINDOW_SECONDS = 15 * 60


class ResolveBody(BaseModel):
    """Optional resolution text for resolving an issue."""

    resolution: str | None = None

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
    kind: str | None = Query(None, pattern="^(comment|vote|review|issue|suggestion)$"),
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

    # Annotate each interaction with reply_count
    items: list[InteractionListResponse] = []
    for interaction in interactions:
        reply_count = await repo.count_replies(interaction.id)
        resp = InteractionListResponse.model_validate(interaction)
        resp.reply_count = reply_count
        items.append(resp)

    return PaginatedResponse(
        items=items, total=len(items), limit=limit, offset=offset
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

    # If signal is set, enforce one active signal per agent per claim
    if body.signal is not None:
        existing_signal = await repo.get_signal_by_agent(claim_id, agent.id)
        if existing_signal is not None:
            raise HTTPException(
                status_code=409,
                detail="You already have an active signal on this claim. "
                "Delete your existing vote/review first.",
            )

    # Validate parent exists and belongs to the same claim (if provided)
    if body.parent_id is not None:
        parent = await repo.get_by_id(body.parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Parent interaction not found")
        if parent.claim_id != claim_id:
            raise HTTPException(
                status_code=422,
                detail="Parent interaction belongs to a different claim",
            )

    # Build attrs with lifecycle defaults
    attrs = dict(body.attrs)
    if body.kind == "issue":
        attrs["issue_status"] = "open"
    elif body.kind == "suggestion":
        attrs["suggestion_status"] = "pending"

    interaction = Interaction(
        claim_id=claim_id,
        author_id=agent.id,
        parent_id=body.parent_id,
        kind=body.kind,
        signal=body.signal,
        confidence=body.confidence,
        weight=1.0,
        author_trust_snapshot=agent.trust_score,
        body=body.body,
        attrs=attrs,
    )
    interaction = await repo.create(interaction)

    # Create references
    for ref in body.references:
        ref_obj = InteractionReference(
            interaction_id=interaction.id,
            ref_type=ref.ref_type,
            ref_id=ref.ref_id,
            role=ref.role,
            attrs=ref.attrs,
        )
        db.add(ref_obj)
    await db.flush()

    await db.commit()

    # Re-fetch with relationships loaded
    interaction = await repo.get_with_references(interaction.id)

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

    reply_count = await repo.count_replies(interaction.id)
    resp = InteractionResponse.model_validate(interaction)
    resp.reply_count = reply_count
    return resp


# ---------------------------------------------------------------------------
# Router 2: /interactions/{interaction_id} (single, patch, delete, actions)
# ---------------------------------------------------------------------------
interactions_router = APIRouter(prefix="/interactions", tags=["interactions"])


async def _get_interaction_or_404(
    interaction_id: UUID, db: AsyncSession
) -> Interaction:
    """Fetch interaction with author loaded, or raise 404."""
    repo = InteractionRepository(db)
    interaction = await repo.get_with_references(interaction_id)
    if interaction is None:
        raise HTTPException(status_code=404, detail="Interaction not found")
    return interaction


async def _get_claim_for_interaction(
    interaction: Interaction, db: AsyncSession
) -> Claim:
    """Fetch the claim associated with an interaction."""
    claim_repo = ClaimRepository(db)
    claim = await claim_repo.get_by_id(interaction.claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Associated claim not found")
    return claim


@interactions_router.get("/{interaction_id}", response_model=InteractionResponse)
async def get_interaction(
    interaction_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    repo = InteractionRepository(db)
    interaction = await repo.get_with_references(interaction_id)
    if interaction is None:
        raise HTTPException(status_code=404, detail="Interaction not found")

    reply_count = await repo.count_replies(interaction.id)
    resp = InteractionResponse.model_validate(interaction)
    resp.reply_count = reply_count
    return resp


@interactions_router.get(
    "/{interaction_id}/thread", response_model=list[InteractionListResponse]
)
async def get_interaction_thread(
    interaction_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[InteractionListResponse]:
    repo = InteractionRepository(db)

    # Verify root interaction exists
    root = await repo.get_by_id(interaction_id)
    if root is None:
        raise HTTPException(status_code=404, detail="Interaction not found")

    thread = await repo.get_thread(interaction_id)

    items: list[InteractionListResponse] = []
    for interaction in thread:
        reply_count = await repo.count_replies(interaction.id)
        resp = InteractionListResponse.model_validate(interaction)
        resp.reply_count = reply_count
        items.append(resp)

    return items


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

    # Enforce the original kind's body limit
    kind_limit = _BODY_LIMIT_BY_KIND.get(interaction.kind, 50_000)
    if len(body.body) > kind_limit:
        raise HTTPException(
            status_code=422,
            detail=f"Body exceeds maximum length of {kind_limit} for kind '{interaction.kind}'",
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
    attrs["edit_history"] = edit_history
    interaction.attrs = attrs
    interaction.body = body.body
    await db.flush()
    await db.commit()

    # Re-fetch
    repo = InteractionRepository(db)
    interaction = await repo.get_with_references(interaction_id)

    await dispatch_event(
        db,
        "interaction.updated",
        {
            "interaction_id": str(interaction_id),
            "claim_id": str(interaction.claim_id),
            "author_id": str(agent.id),
        },
    )

    reply_count = await repo.count_replies(interaction.id)
    resp = InteractionResponse.model_validate(interaction)
    resp.reply_count = reply_count
    return resp


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


# ---------------------------------------------------------------------------
# Action endpoints -- lifecycle state transitions
# ---------------------------------------------------------------------------


@interactions_router.post(
    "/{interaction_id}/accept", response_model=InteractionResponse
)
async def accept_suggestion(
    interaction_id: UUID,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    interaction = await _get_interaction_or_404(interaction_id, db)

    if interaction.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Interaction has been deleted")
    if interaction.kind != "suggestion":
        raise HTTPException(
            status_code=422, detail="Only suggestions can be accepted"
        )

    attrs = dict(interaction.attrs)
    if attrs.get("suggestion_status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Suggestion is '{attrs.get('suggestion_status')}', not 'pending'",
        )

    # Claim author only
    claim = await _get_claim_for_interaction(interaction, db)
    if claim.created_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the claim author can accept suggestions",
        )

    # Create a new claim version with the suggested content
    claim_repo = ClaimRepository(db)
    latest = await claim_repo.get_latest_version(claim.lineage_id)
    next_version = (latest.version if latest else claim.version) + 1

    new_claim = Claim(
        lineage_id=claim.lineage_id,
        version=next_version,
        content=attrs.get("suggested_content", claim.content),
        claim_type=claim.claim_type,
        namespace_id=claim.namespace_id,
        created_by=agent.id,
        formal_content=attrs.get("suggested_formal_content", claim.formal_content),
        supersedes=claim.id,
        status="active",
        attrs={},
        search_tsv=func.to_tsvector(
            "english", attrs.get("suggested_content", claim.content)
        ),
    )
    new_claim = await claim_repo.create(new_claim)

    # Update suggestion status
    attrs["suggestion_status"] = "accepted"
    attrs["accepted_version_id"] = str(new_claim.id)
    interaction.attrs = attrs
    await db.flush()
    await db.commit()

    # Re-fetch
    repo = InteractionRepository(db)
    interaction = await repo.get_with_references(interaction_id)

    await dispatch_event(
        db,
        "interaction.suggestion_accepted",
        {
            "interaction_id": str(interaction_id),
            "claim_id": str(interaction.claim_id),
            "new_version_id": str(new_claim.id),
            "author_id": str(agent.id),
        },
    )

    reply_count = await repo.count_replies(interaction.id)
    resp = InteractionResponse.model_validate(interaction)
    resp.reply_count = reply_count
    return resp


@interactions_router.post(
    "/{interaction_id}/reject", response_model=InteractionResponse
)
async def reject_suggestion(
    interaction_id: UUID,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    interaction = await _get_interaction_or_404(interaction_id, db)

    if interaction.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Interaction has been deleted")
    if interaction.kind != "suggestion":
        raise HTTPException(
            status_code=422, detail="Only suggestions can be rejected"
        )

    attrs = dict(interaction.attrs)
    if attrs.get("suggestion_status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Suggestion is '{attrs.get('suggestion_status')}', not 'pending'",
        )

    # Claim author only
    claim = await _get_claim_for_interaction(interaction, db)
    if claim.created_by != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the claim author can reject suggestions",
        )

    attrs["suggestion_status"] = "rejected"
    interaction.attrs = attrs
    await db.flush()
    await db.commit()

    # Re-fetch
    repo = InteractionRepository(db)
    interaction = await repo.get_with_references(interaction_id)

    await dispatch_event(
        db,
        "interaction.suggestion_rejected",
        {
            "interaction_id": str(interaction_id),
            "claim_id": str(interaction.claim_id),
            "author_id": str(agent.id),
        },
    )

    reply_count = await repo.count_replies(interaction.id)
    resp = InteractionResponse.model_validate(interaction)
    resp.reply_count = reply_count
    return resp


@interactions_router.post(
    "/{interaction_id}/withdraw", response_model=InteractionResponse
)
async def withdraw_suggestion(
    interaction_id: UUID,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    interaction = await _get_interaction_or_404(interaction_id, db)

    if interaction.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Interaction has been deleted")
    if interaction.kind != "suggestion":
        raise HTTPException(
            status_code=422, detail="Only suggestions can be withdrawn"
        )

    attrs = dict(interaction.attrs)
    if attrs.get("suggestion_status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Suggestion is '{attrs.get('suggestion_status')}', not 'pending'",
        )

    # Suggester only
    if interaction.author_id != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the suggestion author can withdraw it",
        )

    attrs["suggestion_status"] = "withdrawn"
    interaction.attrs = attrs
    await db.flush()
    await db.commit()

    # Re-fetch
    repo = InteractionRepository(db)
    interaction = await repo.get_with_references(interaction_id)

    reply_count = await repo.count_replies(interaction.id)
    resp = InteractionResponse.model_validate(interaction)
    resp.reply_count = reply_count
    return resp


@interactions_router.post(
    "/{interaction_id}/resolve", response_model=InteractionResponse
)
async def resolve_issue(
    interaction_id: UUID,
    body: ResolveBody | None = None,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    interaction = await _get_interaction_or_404(interaction_id, db)

    if interaction.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Interaction has been deleted")
    if interaction.kind != "issue":
        raise HTTPException(
            status_code=422, detail="Only issues can be resolved"
        )

    attrs = dict(interaction.attrs)
    current_status = attrs.get("issue_status")
    if current_status not in ("open", "reopened"):
        raise HTTPException(
            status_code=409,
            detail=f"Issue is '{current_status}', not 'open' or 'reopened'",
        )

    # Claim author or issue opener
    claim = await _get_claim_for_interaction(interaction, db)
    if claim.created_by != agent.id and interaction.author_id != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the claim author or issue opener can resolve issues",
        )

    attrs["issue_status"] = "resolved"
    attrs["resolved_by"] = str(agent.id)
    if body is not None and body.resolution is not None:
        attrs["resolution"] = body.resolution
    interaction.attrs = attrs
    await db.flush()
    await db.commit()

    # Re-fetch
    repo = InteractionRepository(db)
    interaction = await repo.get_with_references(interaction_id)

    await dispatch_event(
        db,
        "interaction.issue_resolved",
        {
            "interaction_id": str(interaction_id),
            "claim_id": str(interaction.claim_id),
            "resolved_by": str(agent.id),
        },
    )

    reply_count = await repo.count_replies(interaction.id)
    resp = InteractionResponse.model_validate(interaction)
    resp.reply_count = reply_count
    return resp


@interactions_router.post(
    "/{interaction_id}/reopen", response_model=InteractionResponse
)
async def reopen_issue(
    interaction_id: UUID,
    agent: Agent = Depends(get_current_agent),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    interaction = await _get_interaction_or_404(interaction_id, db)

    if interaction.deleted_at is not None:
        raise HTTPException(status_code=410, detail="Interaction has been deleted")
    if interaction.kind != "issue":
        raise HTTPException(
            status_code=422, detail="Only issues can be reopened"
        )

    attrs = dict(interaction.attrs)
    current_status = attrs.get("issue_status")
    if current_status not in ("resolved", "wont_fix"):
        raise HTTPException(
            status_code=409,
            detail=f"Issue is '{current_status}', not 'resolved' or 'wont_fix'",
        )

    # Issue opener only
    if interaction.author_id != agent.id:
        raise HTTPException(
            status_code=403,
            detail="Only the issue opener can reopen issues",
        )

    # Only one reopen allowed
    if attrs.get("previously_reopened"):
        raise HTTPException(
            status_code=409,
            detail="This issue has already been reopened once and cannot be reopened again",
        )

    attrs["issue_status"] = "reopened"
    attrs["previously_reopened"] = True
    interaction.attrs = attrs
    await db.flush()
    await db.commit()

    # Re-fetch
    repo = InteractionRepository(db)
    interaction = await repo.get_with_references(interaction_id)

    await dispatch_event(
        db,
        "interaction.issue_reopened",
        {
            "interaction_id": str(interaction_id),
            "claim_id": str(interaction.claim_id),
            "reopened_by": str(agent.id),
        },
    )

    reply_count = await repo.count_replies(interaction.id)
    resp = InteractionResponse.model_validate(interaction)
    resp.reply_count = reply_count
    return resp
