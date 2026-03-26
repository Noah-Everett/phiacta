# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Metadata extension data provider for auto-composed entry responses."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.compose import EntryDataProvider
from phiacta.extensions.metadata.repository import MetadataRepository


class MetadataProvider(EntryDataProvider):
    name = "metadata"
    fields = frozenset({"title", "summary"})
    include_in_list = True
    include_in_detail = True
    writable_fields = frozenset({"title", "summary"})
    required_on_create = frozenset({"title"})

    async def get_one(self, entity_id: UUID, db: AsyncSession) -> dict:
        meta = await MetadataRepository(db).get_by_entry_id(entity_id)
        if meta is None:
            return {"title": None, "summary": None}
        return {"title": meta.title, "summary": meta.summary}

    async def get_many(
        self, entity_ids: list[UUID], db: AsyncSession,
    ) -> dict[UUID, dict]:
        meta_map = await MetadataRepository(db).bulk_get_by_entry_ids(entity_ids)
        return {
            eid: {"title": meta_map[eid].title, "summary": meta_map[eid].summary}
            if eid in meta_map
            else {"title": None, "summary": None}
            for eid in entity_ids
        }

    async def write(
        self, entity_id: UUID, data: dict, user_id: UUID, db: AsyncSession,
    ) -> None:
        repo = MetadataRepository(db)
        existing = await repo.get_by_entry_id(entity_id)
        if existing is None:
            # Create path — validate title is present and valid.
            title = data.get("title")
            if title is None:
                raise ValueError("title is required when creating metadata")
            if not isinstance(title, str) or len(title) < 1:
                raise ValueError("title must be a non-empty string")
            if len(title) > 500:
                raise ValueError("title must be at most 500 characters")
            await repo.create(
                entity_id, title, user_id, data.get("summary"),
            )
        else:
            # Update path — validate title if present.
            title = data.get("title")
            if title is not None:
                if not isinstance(title, str) or len(title) < 1:
                    raise ValueError("title must be a non-empty string")
                if len(title) > 500:
                    raise ValueError("title must be at most 500 characters")
            await repo.update_partial(entity_id, data)


entry_data_provider = MetadataProvider()
