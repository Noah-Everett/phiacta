# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.compose import EntryDataProvider
from phiacta.extensions.compiled_content.repository import CompiledContentRepository


class CompiledContentProvider(EntryDataProvider):
    name = "compiled_content"
    fields = frozenset({"compiled_content"})
    include_in_list = False
    include_in_detail = True

    async def get_one(self, entity_id: UUID, db: AsyncSession) -> dict | None:
        repo = CompiledContentRepository(db)
        row = await repo.get_by_entry(entity_id)
        if row is None:
            return {"compiled_content": None}
        return {
            "compiled_content": {
                "format": row.format,
                "file_size": row.file_size,
                "compiled_at": row.compiled_at.isoformat(),
                "source_sha": row.source_sha,
            },
        }

    async def get_many(
        self, entity_ids: list[UUID], db: AsyncSession,
    ) -> dict[UUID, dict]:
        repo = CompiledContentRepository(db)
        meta = await repo.get_metadata_by_entries(entity_ids)
        result: dict[UUID, dict] = {}
        for eid in entity_ids:
            if eid in meta:
                result[eid] = {"compiled_content": meta[eid]}
            else:
                result[eid] = {"compiled_content": None}
        return result
