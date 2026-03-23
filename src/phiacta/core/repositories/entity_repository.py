# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entity repository — encapsulates queries for the entities table."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entity import Entity


class EntityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        entity_type: str,
        parent_id: UUID | None,
        external_ref: str | None,
        created_by: UUID | None,
        id: UUID | None = None,
    ) -> Entity:
        """Create a new entity row.

        If ``id`` is provided, the entity uses that UUID (shared-PK pattern
        for entries and users). Otherwise a new UUID is generated.
        """
        kwargs: dict = {
            "entity_type": entity_type,
            "parent_id": parent_id,
            "external_ref": external_ref,
            "created_by": created_by,
        }
        if id is not None:
            kwargs["id"] = id
        entity = Entity(**kwargs)
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def get_by_id(self, entity_id: UUID) -> Entity | None:
        return await self._session.get(Entity, entity_id)

    async def list_by_type(self, entity_type: str) -> list[Entity]:
        stmt = select(Entity).where(Entity.entity_type == entity_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_parent(self, parent_id: UUID) -> list[Entity]:
        stmt = select(Entity).where(Entity.parent_id == parent_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_ids(self, entity_ids: list[UUID]) -> dict[UUID, Entity]:
        """Batch fetch entities by IDs. Returns a dict keyed by entity ID."""
        if not entity_ids:
            return {}
        stmt = select(Entity).where(Entity.id.in_(entity_ids))
        result = await self._session.execute(stmt)
        return {e.id: e for e in result.scalars().all()}

    async def get_by_external_ref(
        self, parent_id: UUID, external_ref: str,
    ) -> Entity | None:
        stmt = (
            select(Entity)
            .where(Entity.parent_id == parent_id)
            .where(Entity.external_ref == external_ref)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
