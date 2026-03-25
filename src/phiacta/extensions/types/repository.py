# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Types repository — queries for the extension_types table."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.extensions.types.models import ExtensionType


class TypeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_entry_id(self, entry_id: UUID) -> ExtensionType | None:
        stmt = select(ExtensionType).where(ExtensionType.entity_id == entry_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, entry_id: UUID, entry_type: str, created_by: UUID) -> ExtensionType:
        ext_type = ExtensionType(entity_id=entry_id, entry_type=entry_type, created_by=created_by)
        self.session.add(ext_type)
        await self.session.flush()
        return ext_type

    async def upsert(self, entry_id: UUID, entry_type: str, created_by: UUID) -> ExtensionType:
        existing = await self.get_by_entry_id(entry_id)
        if existing is not None:
            existing.entry_type = entry_type
            await self.session.flush()
            return existing
        return await self.create(entry_id, entry_type, created_by)

    async def bulk_get_by_entry_ids(self, entry_ids: list[UUID]) -> dict[UUID, ExtensionType]:
        if not entry_ids:
            return {}
        stmt = select(ExtensionType).where(ExtensionType.entity_id.in_(entry_ids))
        result = await self.session.execute(stmt)
        return {t.entity_id: t for t in result.scalars().all()}
