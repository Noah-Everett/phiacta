# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.entry_ref import EntryRef
from phiacta.repositories.base import BaseRepository


class EntryRefRepository(BaseRepository[EntryRef]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, EntryRef)

    async def list_by_entry(
        self, entry_id: UUID, *, direction: str = "both",
        limit: int = 200, offset: int = 0,
    ) -> list[EntryRef]:
        if direction == "outgoing":
            stmt = select(EntryRef).where(EntryRef.from_entry_id == entry_id)
        elif direction == "incoming":
            stmt = select(EntryRef).where(EntryRef.to_entry_id == entry_id)
        else:
            stmt = select(EntryRef).where(
                (EntryRef.from_entry_id == entry_id)
                | (EntryRef.to_entry_id == entry_id)
            )
        result = await self.session.execute(stmt.limit(limit).offset(offset))
        return list(result.scalars().all())

    async def list_by_rel(
        self, rel: str, *, limit: int = 200, offset: int = 0
    ) -> list[EntryRef]:
        result = await self.session.execute(
            select(EntryRef)
            .where(EntryRef.rel == rel)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_all(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(EntryRef)
        )
        return result.scalar_one()

    async def count_by_entry(self, entry_id: UUID, *, direction: str = "both") -> int:
        if direction == "outgoing":
            stmt = select(func.count()).where(EntryRef.from_entry_id == entry_id)
        elif direction == "incoming":
            stmt = select(func.count()).where(EntryRef.to_entry_id == entry_id)
        else:
            stmt = select(func.count()).where(
                (EntryRef.from_entry_id == entry_id)
                | (EntryRef.to_entry_id == entry_id)
            )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def delete_outgoing(self, entry_id: UUID) -> int:
        """Delete all outgoing refs (from_entry_id = entry_id). Returns count deleted."""
        result = await self.session.execute(
            delete(EntryRef).where(EntryRef.from_entry_id == entry_id)
        )
        await self.session.flush()
        return result.rowcount

    async def count_by_rel(self, rel: str) -> int:
        result = await self.session.execute(
            select(func.count()).where(EntryRef.rel == rel)
        )
        return result.scalar_one()
