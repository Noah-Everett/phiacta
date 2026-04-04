# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.pagination import keyset_condition
from phiacta.core.visibility import discovery_condition
from phiacta.core.models.entry import Entry
from phiacta.core.models.user import User
from phiacta.core.repositories.base import BaseRepository


class EntryRepository(BaseRepository[Entry]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Entry)

    SORTABLE_COLUMNS = {"created_at", "updated_at"}

    async def list_entries(
        self,
        limit: int = 50,
        visibility: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        user: User | None = None,
        cursor_sort_value: str | None = None,
        cursor_id: UUID | None = None,
        # Legacy offset param — ignored when cursor is provided
        offset: int = 0,
    ) -> list[Entry]:
        if sort_by not in self.SORTABLE_COLUMNS:
            sort_by = "created_at"
        if sort_order not in ("asc", "desc"):
            sort_order = "desc"

        stmt = select(Entry)
        if visibility is not None:
            stmt = stmt.where(Entry.visibility == visibility)
        stmt = stmt.where(discovery_condition(user))

        column = getattr(Entry, sort_by)
        descending = sort_order == "desc"

        # Keyset pagination: apply cursor condition
        if cursor_sort_value is not None and cursor_id is not None:
            cursor_dt = datetime.fromisoformat(cursor_sort_value)
            stmt = stmt.where(
                keyset_condition(column, Entry.id, cursor_dt, cursor_id, descending)
            )

        stmt = stmt.order_by(
            column.desc() if descending else column.asc(),
            Entry.id.desc() if descending else Entry.id.asc(),
        )
        # Fetch limit+1 to detect has_more
        stmt = stmt.limit(limit + 1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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
