# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.core.repositories.base import BaseRepository


class EntryRepository(BaseRepository[Entry]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Entry)

    async def list_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        layout_hint: str | None = None,
        status: str | None = "active",
    ) -> list[Entry]:
        stmt = select(Entry)
        if layout_hint is not None:
            stmt = stmt.where(Entry.layout_hint == layout_hint)
        if status is not None:
            stmt = stmt.where(Entry.status == status)
        stmt = stmt.order_by(Entry.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_entries(
        self,
        layout_hint: str | None = None,
        status: str | None = "active",
    ) -> int:
        stmt = select(func.count()).select_from(Entry)
        if layout_hint is not None:
            stmt = stmt.where(Entry.layout_hint == layout_hint)
        if status is not None:
            stmt = stmt.where(Entry.status == status)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_all_for_reconciliation(self) -> list[Entry]:
        """Return all entries (no status filter, no limit) for reconciliation.

        Returns lightweight Entry ORM objects.  Callers should avoid accessing
        ``content_cache`` (can be large) unless re-ingesting.
        """
        result = await self.session.execute(select(Entry))
        return list(result.scalars().all())

    async def update_repo_status(
        self, entry_id: UUID, *, repo_status: str, forgejo_repo_id: int | None = None,
        current_head_sha: str | None = None,
    ) -> None:
        entry = await self.get_by_id(entry_id)
        if entry is None:
            return
        entry.repo_status = repo_status
        if forgejo_repo_id is not None:
            entry.forgejo_repo_id = forgejo_repo_id
        if current_head_sha is not None:
            entry.current_head_sha = current_head_sha
        await self.session.flush()
