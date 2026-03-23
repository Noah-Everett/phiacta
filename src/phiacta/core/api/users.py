# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.db.session import get_db
from phiacta.core.repositories.activity_repository import ActivityRepository
from phiacta.core.repositories.entity_repository import EntityRepository
from phiacta.core.repositories.user_repository import UserRepository
from phiacta.core.schemas.activity import ActivityFeedResponse, ActivityItem
from phiacta.core.schemas.auth import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.get("/{user_id}/activity", response_model=ActivityFeedResponse)
async def get_user_activity(
    user_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    before: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> ActivityFeedResponse:
    """Get a user's activity feed, newest first, with cursor pagination.

    Public endpoint — no authentication required.
    """
    # Verify user exists
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Query activity
    activity_repo = ActivityRepository(db)
    items, next_cursor = await activity_repo.list_by_actor(
        actor_id=user_id, limit=limit, before=before,
    )

    # Batch fetch entities to avoid N+1 queries
    entity_repo = EntityRepository(db)
    entity_ids = list({a.entity_id for a in items})
    entities_by_id = await entity_repo.get_by_ids(entity_ids)

    result_items: list[ActivityItem] = []
    for a in items:
        entity = entities_by_id.get(a.entity_id)
        result_items.append(ActivityItem(
            id=a.id,
            action=a.action,
            entity_type=entity.entity_type if entity else "unknown",
            entity_id=a.entity_id,
            parent_id=entity.parent_id if entity else None,
            metadata=a.activity_metadata,
            created_at=a.created_at,
        ))

    return ActivityFeedResponse(items=result_items, next_cursor=next_cursor)
