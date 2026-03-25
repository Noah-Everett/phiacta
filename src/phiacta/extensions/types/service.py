# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Types service — business logic for type operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.extensions.types.models import ExtensionType
from phiacta.extensions.types.repository import TypeRepository


class TypeService:
    def __init__(self, session: AsyncSession) -> None:
        self._type_repo = TypeRepository(session)
        self._entry_repo = EntryRepository(session)

    async def create_for_entry(self, entry_id: UUID, entry_type: str, user_id: UUID) -> ExtensionType:
        return await self._type_repo.create(entry_id, entry_type, user_id)

    async def set_type(self, entry_id: UUID, entry_type: str, user_id: UUID) -> ExtensionType:
        entry = await self._entry_repo.get_by_id(entry_id)
        if entry is None:
            raise LookupError("Entry not found")
        if entry.repo_status != "ready":
            raise ValueError("Entry repository is not yet ready")
        if entry.created_by != user_id:
            raise PermissionError("Only the entry owner can set type")
        return await self._type_repo.upsert(entry_id, entry_type, user_id)
