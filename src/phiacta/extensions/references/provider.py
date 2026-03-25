# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""References extension data provider for auto-composed entry responses."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.compose import EntryDataProvider
from phiacta.extensions.references.repository import ReferenceRepository


class ReferenceProvider(EntryDataProvider):
    name = "references"
    fields = frozenset({"references"})
    include_in_list = False
    include_in_detail = True

    async def get_one(self, entity_id: UUID, db: AsyncSession) -> dict:
        refs = await ReferenceRepository(db).list_by_entry(entity_id)
        return {"references": [_ref_to_dict(r) for r in refs]}

    async def get_many(
        self, entity_ids: list[UUID], db: AsyncSession,
    ) -> dict[UUID, dict]:
        ref_map = await ReferenceRepository(db).bulk_get_by_entry_ids(entity_ids)
        return {
            eid: {"references": [_ref_to_dict(r) for r in ref_map.get(eid, [])]}
            for eid in entity_ids
        }


def _ref_to_dict(ref) -> dict:  # noqa: ANN001
    return {
        "id": ref.id,
        "from_entity_id": ref.from_entity_id,
        "to_entity_id": ref.to_entity_id,
        "rel": ref.rel,
        "version_sha": ref.version_sha,
        "note": ref.note,
        "created_by": ref.created_by,
        "created_at": ref.created_at,
    }


entry_data_provider = ReferenceProvider()
