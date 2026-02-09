# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newpublishing.models.base import Base


class BaseRepository[T: Base]:
    def __init__(self, session: AsyncSession, model: type[T]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, entity_id: UUID) -> T | None:
        return await self.session.get(self.model, entity_id)

    async def create(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[T]:
        result = await self.session.execute(select(self.model).limit(limit).offset(offset))
        return list(result.scalars().all())

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()
