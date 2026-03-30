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

from phiacta.core.auth.dependencies import get_optional_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.repositories.activity_repository import ActivityRepository
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.repositories.entity_repository import EntityRepository
from phiacta.core.repositories.user_repository import UserRepository
from phiacta.core.schemas.activity import ActivityFeedResponse, ActivityItem
from phiacta.core.visibility import check_entry_access

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
        entry_repo = EntryRepository(db)
        for eid in candidate_entry_ids:
            entry_obj = await entry_repo.get_by_id(eid)
            if entry_obj is None:
                visible_entries[eid] = True  # entry deleted, allow activity
            else:
                try:
                    check_entry_access(entry_obj, user)
                    visible_entries[eid] = True
                except HTTPException:
                    visible_entries[eid] = False

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
            action=a.action,
            entity_type=ent.entity_type if ent else "unknown",
            entity_id=a.entity_id,
            parent_id=ent.parent_id if ent else None,
            metadata=a.activity_metadata,
            created_at=a.created_at,
        ))

    return ActivityFeedResponse(items=result_items, next_cursor=next_cursor)
