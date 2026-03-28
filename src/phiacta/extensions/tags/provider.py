# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tags extension data provider for auto-composed entry responses."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.compose import EntryDataProvider
from phiacta.extensions.tags.models import ExtensionTag
from phiacta.extensions.tags.repository import TagRepository


class TagProvider(EntryDataProvider):
    name = "tags"
    fields = frozenset({"tags"})
    include_in_list = True
    include_in_detail = True
    writable_fields = frozenset({"tags"})
    filterable_fields = frozenset({"tags"})

    def apply_search_filter(
        self, stmt: Any, entry_id_col: Any, field: str, value: str,
    ) -> Any:
        # value format: "tag1,tag2" with optional ";mode=and" suffix
        # e.g. "math,physics;mode=and" or just "math,physics" (default OR)
        mode = "or"
        raw = value
        if ";mode=" in raw:
            raw, _, mode_str = raw.partition(";mode=")
            if mode_str in ("and", "or"):
                mode = mode_str

        tags = [t.strip().lower() for t in raw.split(",") if t.strip()]
        if not tags:
            return stmt

        if mode == "and":
            # Entry must have ALL tags
            subq = (
                select(ExtensionTag.entity_id)
                .where(ExtensionTag.tag.in_(tags))
                .group_by(ExtensionTag.entity_id)
                .having(func.count(func.distinct(ExtensionTag.tag)) == len(tags))
            ).scalar_subquery()
        else:
            # Entry must have ANY tag
            subq = (
                select(ExtensionTag.entity_id)
                .where(ExtensionTag.tag.in_(tags))
                .distinct()
            ).scalar_subquery()

        return stmt.where(entry_id_col.in_(subq))

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
