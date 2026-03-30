# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.core.repositories.base import BaseRepository


class EntryRepository(BaseRepository[Entry]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Entry)

    SORTABLE_COLUMNS = {"created_at", "updated_at"}

    def _archive_visibility(self, viewer_id: UUID | None):
        """Archived entries are only visible to their owner."""
        if viewer_id is None:
            return Entry.status != "archived"
        return or_(Entry.status != "archived", Entry.created_by == viewer_id)

    async def list_entries(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = "active",
        sort_by: str = "created_at",
        sort_order: str = "desc",
        viewer_id: UUID | None = None,
    ) -> list[Entry]:
        if sort_by not in self.SORTABLE_COLUMNS:
            sort_by = "created_at"
        if sort_order not in ("asc", "desc"):
            sort_order = "desc"
        stmt = select(Entry)
        if status is not None:
            stmt = stmt.where(Entry.status == status)
        stmt = stmt.where(self._archive_visibility(viewer_id))
        column = getattr(Entry, sort_by)
        stmt = stmt.order_by(column.asc() if sort_order == "asc" else column.desc())
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_entries(
        self, status: str | None = "active", viewer_id: UUID | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Entry)
        if status is not None:
            stmt = stmt.where(Entry.status == status)
        stmt = stmt.where(self._archive_visibility(viewer_id))
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def list_all_for_reconciliation(self) -> list[Entry]:
        result = await self.session.execute(select(Entry))
        return list(result.scalars().all())

    async def update_repo_status(
        self, entry_id: UUID, *, repo_status: str,
        forgejo_repo_id: int | None = None, current_head_sha: str | None = None,
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
