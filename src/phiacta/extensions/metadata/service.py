# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Metadata service — business logic for metadata operations."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.extensions.metadata.models import ExtensionMetadata
from phiacta.extensions.metadata.repository import MetadataRepository


class MetadataService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._metadata_repo = MetadataRepository(session)
        self._entry_repo = EntryRepository(session)

    async def set_metadata(
        self, entry_id: UUID, title: str, user_id: UUID, summary: str | None = None,
    ) -> ExtensionMetadata:
        entry = await self._entry_repo.get_by_id(entry_id)
        if entry is None:
            raise LookupError("Entry not found")
        if entry.repo_status != "ready":
            raise ValueError("Entry repository is not yet ready")
        if entry.created_by != user_id:
            raise PermissionError("Only the entry owner can update metadata")
        return await self._metadata_repo.upsert(entry_id, title, user_id, summary)

    async def update_metadata(
        self, entry_id: UUID, updates: dict, user_id: UUID,
    ) -> ExtensionMetadata:
        entry = await self._entry_repo.get_by_id(entry_id)
        if entry is None:
            raise LookupError("Entry not found")
        if entry.repo_status != "ready":
            raise ValueError("Entry repository is not yet ready")
        if entry.created_by != user_id:
            raise PermissionError("Only the entry owner can update metadata")
        result = await self._metadata_repo.update_partial(entry_id, updates)
        if result is None:
            raise LookupError("Metadata not found for this entry")
        return result
