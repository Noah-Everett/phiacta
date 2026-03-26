# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Activity feed API.

Public endpoint for querying the activity log. Supports filtering
by actor (user) and entity, with cursor pagination.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.db.session import get_db
from phiacta.core.repositories.activity_repository import ActivityRepository
from phiacta.core.repositories.entity_repository import EntityRepository
from phiacta.core.repositories.user_repository import UserRepository
from phiacta.core.schemas.activity import ActivityFeedResponse, ActivityItem

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=ActivityFeedResponse)
async def get_activity(
    actor: UUID | None = Query(None, description="Filter by actor (user ID)"),
    entity: UUID | None = Query(None, description="Filter by entity ID"),
    limit: int = Query(50, ge=1, le=100),
    before: UUID | None = Query(None, description="Cursor for pagination"),
    db: AsyncSession = Depends(get_db),
) -> ActivityFeedResponse:
    """Query the activity feed. At least one filter (actor or entity) is required.

    Public endpoint — no authentication required.
    """
    if actor is None and entity is None:
        raise HTTPException(
            status_code=400,
            detail="At least one filter required: actor or entity",
        )

    activity_repo = ActivityRepository(db)
    entity_repo = EntityRepository(db)

    if actor is not None:
        # Verify user exists
        user_repo = UserRepository(db)
        user = await user_repo.get_by_id(actor)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        items, next_cursor = await activity_repo.list_by_actor(
            actor_id=actor, limit=limit, before=before,
        )
    else:
        # entity filter
        target = await entity_repo.get_by_id(entity)  # type: ignore[arg-type]
        if target is None:
            raise HTTPException(status_code=404, detail="Entity not found")

        all_items = await activity_repo.list_by_entity(entity_id=entity)  # type: ignore[arg-type]
        # Manual cursor pagination for entity queries
        if before is not None:
            skip = True
            filtered = []
            for a in all_items:
                if skip:
                    if a.id == before:
                        skip = False
                    continue
                filtered.append(a)
            all_items = filtered
        items = all_items[:limit]
        next_cursor = items[-1].id if len(items) == limit and len(all_items) > limit else None

    # Batch fetch entities to avoid N+1
    entity_ids = list({a.entity_id for a in items})
    entities_by_id = await entity_repo.get_by_ids(entity_ids)

    result_items: list[ActivityItem] = []
    for a in items:
        ent = entities_by_id.get(a.entity_id)
        result_items.append(ActivityItem(
            id=a.id,
            action=a.action,
            entity_type=ent.entity_type if ent else "unknown",
            entity_id=a.entity_id,
            parent_id=ent.parent_id if ent else None,
            metadata=a.activity_metadata,
            created_at=a.created_at,
        ))

    return ActivityFeedResponse(items=result_items, next_cursor=next_cursor)
