# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.reference import Reference
from phiacta.repositories.base import BaseRepository


class ReferenceRepository(BaseRepository[Reference]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Reference)

    async def list_by_source_uri(
        self, source_uri: str, *, limit: int = 200, offset: int = 0
    ) -> list[Reference]:
        result = await self.session.execute(
            select(Reference)
            .where(Reference.source_uri == source_uri)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_target_uri(
        self, target_uri: str, *, limit: int = 200, offset: int = 0
    ) -> list[Reference]:
        result = await self.session.execute(
            select(Reference)
            .where(Reference.target_uri == target_uri)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_by_claim(
        self, claim_id: UUID, *, direction: str = "both",
        limit: int = 200, offset: int = 0,
    ) -> list[Reference]:
        if direction == "outgoing":
            stmt = select(Reference).where(Reference.source_claim_id == claim_id)
        elif direction == "incoming":
            stmt = select(Reference).where(Reference.target_claim_id == claim_id)
        else:
            stmt = select(Reference).where(
                (Reference.source_claim_id == claim_id)
                | (Reference.target_claim_id == claim_id)
            )
        result = await self.session.execute(stmt.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def list_by_role(
        self, role: str, *, limit: int = 200, offset: int = 0
    ) -> list[Reference]:
        result = await self.session.execute(
            select(Reference)
            .where(Reference.role == role)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Reference)
        )
        return result.scalar_one()
