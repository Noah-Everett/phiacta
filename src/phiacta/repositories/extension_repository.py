# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.extension import Extension
from phiacta.repositories.base import BaseRepository


class ExtensionRepository(BaseRepository[Extension]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Extension)

    async def get_by_name_version(self, name: str, version: str) -> Extension | None:
        result = await self.session.execute(
            select(Extension).where(
                Extension.name == name,
                Extension.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Extension | None:
        result = await self.session.execute(
            select(Extension).where(Extension.name == name)
        )
        return result.scalar_one_or_none()

    async def count_all(self) -> int:
        """Return the total number of registered extensions."""
        result = await self.session.execute(
            select(func.count()).select_from(Extension)
        )
        return result.scalar_one()

    async def count_by_agent(self, agent_id: UUID) -> int:
        """Return the number of extensions registered by a given agent."""
        result = await self.session.execute(
            select(func.count()).where(Extension.registered_by == agent_id)
        )
        return result.scalar_one()

    async def list_by_type(
        self,
        extension_type: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Extension]:
        result = await self.session.execute(
            select(Extension)
            .where(Extension.extension_type == extension_type)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_healthy(self) -> list[Extension]:
        result = await self.session.execute(
            select(Extension).where(Extension.health_status == "healthy")
        )
        return list(result.scalars().all())

    async def list_by_event(self, event_type: str) -> list[Extension]:
        """Return healthy extensions subscribed to a given event type."""
        result = await self.session.execute(
            select(Extension).where(
                Extension.subscribed_events.op("@>")(
                    cast(literal(f'["{event_type}"]'), JSONB)
                ),
                Extension.health_status == "healthy",
            )
        )
        return list(result.scalars().all())
