# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""References service — business logic for reference operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.extensions.references.models import ExtensionReference
from phiacta.extensions.references.repository import ReferenceRepository


class ReferenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._ref_repo = ReferenceRepository(session)
        self._entry_repo = EntryRepository(session)

    async def create_reference(
        self, from_entry_id: UUID, to_entry_id: UUID, rel: str, user_id: UUID,
        version_sha: str | None = None, note: str | None = None,
    ) -> ExtensionReference:
        if from_entry_id == to_entry_id:
            raise ValueError("Cannot create a self-reference")
        source = await self._entry_repo.get_by_id(from_entry_id)
        if source is None:
            raise LookupError("Source entry not found")
        if source.repo_status != "ready":
            raise ValueError("Source entry repository is not yet ready")
        if source.created_by != user_id:
            raise PermissionError("Only the source entry owner can create references")
        target = await self._entry_repo.get_by_id(to_entry_id)
        if target is None:
            raise LookupError("Target entry not found")
        return await self._ref_repo.create(
            from_entry_id, to_entry_id, rel, user_id, version_sha, note,
        )

    async def delete_reference(self, ref_id: UUID, user_id: UUID) -> None:
        ref = await self._ref_repo.get_by_id(ref_id)
        if ref is None:
            raise LookupError("Reference not found")
        source = await self._entry_repo.get_by_id(ref.from_entity_id)
        if source is None:
            raise LookupError("Source entry not found")
        if source.created_by != user_id:
            raise PermissionError("Only the source entry owner can delete references")
        await self._ref_repo.delete_by_id(ref_id)
