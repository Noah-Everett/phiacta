# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Metadata repository — queries for the extension_metadata table."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.extensions.metadata.models import ExtensionMetadata

logger = logging.getLogger(__name__)


class MetadataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_entry_id(self, entry_id: UUID) -> ExtensionMetadata | None:
        stmt = select(ExtensionMetadata).where(ExtensionMetadata.entity_id == entry_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self, entry_id: UUID, title: str, created_by: UUID, summary: str | None = None,
    ) -> ExtensionMetadata:
        metadata = ExtensionMetadata(
            entity_id=entry_id, title=title, summary=summary, created_by=created_by,
        )
        self.session.add(metadata)
        await self.session.flush()
        return metadata

    async def upsert(
        self, entry_id: UUID, title: str, created_by: UUID, summary: str | None = None,
    ) -> ExtensionMetadata:
        existing = await self.get_by_entry_id(entry_id)
        if existing is not None:
            existing.title = title
            existing.summary = summary
            await self.session.flush()
            return existing
        return await self.create(entry_id, title, created_by, summary)

    async def update_partial(self, entry_id: UUID, updates: dict) -> ExtensionMetadata | None:
        existing = await self.get_by_entry_id(entry_id)
        if existing is None:
            return None
        for key, value in updates.items():
            if key == "title" and value is None:
                continue  # title is NOT NULL -- cannot clear
            if key in ("title", "summary"):
                setattr(existing, key, value)
        await self.session.flush()
        return existing

    async def bulk_get_by_entry_ids(self, entry_ids: list[UUID]) -> dict[UUID, ExtensionMetadata]:
        if not entry_ids:
            return {}
        stmt = select(ExtensionMetadata).where(ExtensionMetadata.entity_id.in_(entry_ids))
        result = await self.session.execute(stmt)
        return {m.entity_id: m for m in result.scalars().all()}
