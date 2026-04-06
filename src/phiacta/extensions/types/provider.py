# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Types extension data provider for auto-composed entry responses."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.compose import EntryDataProvider
from phiacta.extensions.types.models import ExtensionType
from phiacta.extensions.types.repository import TypeRepository


class TypeProvider(EntryDataProvider):
    name = "types"
    fields = frozenset({"entry_type"})
    include_in_list = True
    include_in_detail = True
    writable_fields = frozenset({"entry_type"})
    filterable_fields = frozenset({"entry_type"})

    def apply_search_filter(
        self, stmt: Any, entry_id_col: Any, field: str, value: str,
    ) -> Any:
        values = [v.strip() for v in value.split(",") if v.strip()]
        if not values:
            return stmt
        # Use a subquery so this works regardless of whether ExtensionType
        # is already joined (enrichment) or not (count query).
        subq = (
            select(ExtensionType.entity_id)
            .where(ExtensionType.entry_type.in_(values))
        ).scalar_subquery()
        return stmt.where(entry_id_col.in_(subq))

    async def get_one(self, entity_id: UUID, db: AsyncSession) -> dict:
        ext_type = await TypeRepository(db).get_by_entry_id(entity_id)
        if ext_type is None:
            return {"entry_type": None}
        return {"entry_type": ext_type.entry_type}

    async def get_many(
        self, entity_ids: list[UUID], db: AsyncSession,
    ) -> dict[UUID, dict]:
        type_map = await TypeRepository(db).bulk_get_by_entry_ids(entity_ids)
        return {
            eid: {"entry_type": type_map[eid].entry_type}
            if eid in type_map
            else {"entry_type": None}
            for eid in entity_ids
        }

    async def write(
        self, entity_id: UUID, data: dict, user_id: UUID, db: AsyncSession,
    ) -> None:
        repo = TypeRepository(db)
        entry_type = data["entry_type"]
        if not isinstance(entry_type, str) or not entry_type.strip():
            raise ValueError("entry_type must be a non-empty string")
        await repo.upsert(entity_id, entry_type.strip(), user_id)


entry_data_provider = TypeProvider()
