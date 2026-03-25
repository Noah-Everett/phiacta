# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tags extension data provider for auto-composed entry responses."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.compose import EntryDataProvider
from phiacta.extensions.tags.repository import TagRepository


class TagProvider(EntryDataProvider):
    name = "tags"
    fields = frozenset({"tags"})
    include_in_list = True
    include_in_detail = True
    writable_fields = frozenset({"tags"})

    async def get_one(self, entity_id: UUID, db: AsyncSession) -> dict:
        tags = await TagRepository(db).list_by_entry(entity_id)
        return {"tags": [t.tag for t in tags]}

    async def get_many(
        self, entity_ids: list[UUID], db: AsyncSession,
    ) -> dict[UUID, dict]:
        tag_map = await TagRepository(db).bulk_get_by_entry_ids(entity_ids)
        return {
            eid: {"tags": [t.tag for t in tag_map.get(eid, [])]}
            for eid in entity_ids
        }

    async def write(
        self, entity_id: UUID, data: dict, user_id: UUID, db: AsyncSession,
    ) -> None:
        repo = TagRepository(db)
        await repo.replace_tags(entity_id, data["tags"], user_id)


entry_data_provider = TagProvider()
