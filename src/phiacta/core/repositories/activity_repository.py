# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Activity repository — encapsulates queries for the activity table.

Does NOT inherit from BaseRepository because activity operations have
different semantics (append-only, cursor-based pagination, no update/delete).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.activity import Activity


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        actor_id: UUID,
        action: str,
        entity_id: UUID,
        metadata: dict | None,
    ) -> Activity:
        """Append an activity record."""
        activity = Activity(
            actor_id=actor_id,
            action=action,
            entity_id=entity_id,
            activity_metadata=metadata,
        )
        self._session.add(activity)
        await self._session.flush()
        return activity

    async def list_by_actor(
        self,
        actor_id: UUID,
        limit: int = 50,
        before: UUID | None = None,
    ) -> tuple[list[Activity], UUID | None]:
        """List activity for an actor, newest first, with cursor pagination.

        ``before`` is the ID of the last item from the previous page.
        Returns (items, next_cursor) where next_cursor is the ID to pass
        as ``before`` for the next page, or None if no more items.
        """
        stmt = (
            select(Activity)
            .where(Activity.actor_id == actor_id)
            .order_by(Activity.created_at.desc(), Activity.id.desc())
            .limit(limit + 1)  # fetch one extra to detect next page
        )

        if before is not None:
            # Get the cursor row to find its created_at
            cursor_row = await self._session.get(Activity, before)
            if cursor_row is not None:
                stmt = stmt.where(
                    (Activity.created_at < cursor_row.created_at)
                    | (
                        (Activity.created_at == cursor_row.created_at)
                        & (Activity.id < cursor_row.id)
                    )
                )

        result = await self._session.execute(stmt)
        items = list(result.scalars().all())

        if len(items) > limit:
            # There are more items — return cursor for next page
            items = items[:limit]
            next_cursor = items[-1].id
        else:
            next_cursor = None

        return items, next_cursor

    async def list_by_entity(self, entity_id: UUID) -> list[Activity]:
        """List all activity for an entity, newest first."""
        stmt = (
            select(Activity)
            .where(Activity.entity_id == entity_id)
            .order_by(Activity.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_actor(self, actor_id: UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(Activity)
            .where(Activity.actor_id == actor_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
