# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Activity repository — encapsulates queries for the activity table.

Does NOT inherit from BaseRepository because activity operations have
different semantics (append-only, cursor-based pagination, no update/delete).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
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
        cursor_created_at: datetime | None = None,
        cursor_id: UUID | None = None,
    ) -> list[Activity]:
        """List activity for an actor, newest first, with keyset pagination.

        Returns limit+1 items so the caller can detect has_more.
        """
        stmt = (
            select(Activity)
            .where(Activity.actor_id == actor_id)
            .order_by(Activity.created_at.desc(), Activity.id.desc())
            .limit(limit + 1)
        )

        if cursor_created_at is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    Activity.created_at < cursor_created_at,
                    and_(
                        Activity.created_at == cursor_created_at,
                        Activity.id < cursor_id,
                    ),
                )
            )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_entity(
        self,
        entity_id: UUID,
        limit: int = 50,
        cursor_created_at: datetime | None = None,
        cursor_id: UUID | None = None,
    ) -> list[Activity]:
        """List activity for an entity, newest first, with keyset pagination.

        Returns limit+1 items so the caller can detect has_more.
        """
        stmt = (
            select(Activity)
            .where(Activity.entity_id == entity_id)
            .order_by(Activity.created_at.desc(), Activity.id.desc())
            .limit(limit + 1)
        )

        if cursor_created_at is not None and cursor_id is not None:
            stmt = stmt.where(
                or_(
                    Activity.created_at < cursor_created_at,
                    and_(
                        Activity.created_at == cursor_created_at,
                        Activity.id < cursor_id,
                    ),
                )
            )

        result = await self._session.execute(stmt)
        return list(result.scalars().all())
