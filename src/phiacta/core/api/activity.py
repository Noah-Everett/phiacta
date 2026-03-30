# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Activity feed API.

Public endpoint for querying the activity log. Supports filtering
by actor (user) and entity, with cursor pagination.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.auth.dependencies import get_optional_user
from phiacta.core.db.session import get_db
from phiacta.core.models.entry import Entry
from phiacta.core.models.user import User
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
    user: User | None = Depends(get_optional_user),
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
        # Verify actor user exists (don't shadow the `user` param)
        user_repo = UserRepository(db)
        actor_user = await user_repo.get_by_id(actor)
        if actor_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        items, next_cursor = await activity_repo.list_by_actor(
            actor_id=actor, limit=limit, before=before,
        )
    else:
        # entity filter
        target = await entity_repo.get_by_id(entity)  # type: ignore[arg-type]
        if target is None:
            raise HTTPException(status_code=404, detail="Entity not found")

        items, next_cursor = await activity_repo.list_by_entity(
            entity_id=entity, limit=limit, before=before,  # type: ignore[arg-type]
        )

    # Batch fetch entities to avoid N+1
    entity_ids = list({a.entity_id for a in items})
    entities_by_id = await entity_repo.get_by_ids(entity_ids)

    # Collect entry IDs referenced by activity items (directly or via parent)
    # to filter out items referencing private entries the caller can't see.
    candidate_entry_ids: set[UUID] = set()
    for a in items:
        ent = entities_by_id.get(a.entity_id)
        if ent is not None:
            if ent.entity_type == "entry":
                candidate_entry_ids.add(a.entity_id)
            elif ent.parent_id is not None:
                candidate_entry_ids.add(ent.parent_id)

    # Batch-load entries for visibility checks
    visible_entries: dict[UUID, bool] = {}
    if candidate_entry_ids:
        stmt = select(Entry).where(Entry.id.in_(list(candidate_entry_ids)))
        result = await db.execute(stmt)
        entries_by_id = {e.id: e for e in result.scalars().all()}

        for eid in candidate_entry_ids:
            entry_obj = entries_by_id.get(eid)
            if entry_obj is None:
                visible_entries[eid] = True  # entry deleted, allow activity
            else:
                visible_entries[eid] = (
                    entry_obj.visibility == "public"
                    or (user is not None and entry_obj.created_by == user.id)
                )

    result_items: list[ActivityItem] = []
    for a in items:
        ent = entities_by_id.get(a.entity_id)
        # Check visibility: skip items referencing private entries
        if ent is not None:
            if ent.entity_type == "entry" and not visible_entries.get(a.entity_id, True):
                continue
            if ent.parent_id is not None and not visible_entries.get(ent.parent_id, True):
                continue
        result_items.append(ActivityItem(
            id=a.id,
            actor_id=a.actor_id,
            action=a.action,
            entity_type=ent.entity_type if ent else "unknown",
            entity_id=a.entity_id,
            parent_id=ent.parent_id if ent else None,
            metadata=a.activity_metadata,
            created_at=a.created_at,
        ))

    # Compute next_cursor AFTER filtering
    filtered_cursor = result_items[-1].id if result_items and len(result_items) == limit else None
    return ActivityFeedResponse(items=result_items, next_cursor=filtered_cursor)
