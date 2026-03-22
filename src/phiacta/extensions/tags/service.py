# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tag service — business logic for tag operations.

The service validates entry existence and ownership, normalizes tags,
and delegates to the repository for persistence. Only the PUT endpoint
goes through the service; read-only endpoints access the repository
directly from the router.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.extensions.tags.models import ExtensionTag
from phiacta.extensions.tags.repository import TagRepository


def normalize_tags(tags: list[str]) -> list[str]:
    """Normalize tags: lowercase, strip whitespace, deduplicate, filter empty.

    Raises ``ValueError`` if any tag contains a comma (reserved as query
    separator in the find-by-tags endpoint).
    """
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if "," in tag:
            raise ValueError(
                "Tags must not contain commas "
                "(comma is reserved as query separator)"
            )
        normalized = tag.strip().lower()
        if not normalized:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


class TagService:
    """Business logic for tag lifecycle operations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tag_repo = TagRepository(session)
        self._entry_repo = EntryRepository(session)

    async def set_tags(
        self, entry_id: UUID, tags: list[str], user_id: UUID
    ) -> list[ExtensionTag]:
        """Replace all tags on an entry.

        Validates that the entry exists, is ready, and the user is the owner.
        Normalizes tags before persisting.

        Raises:
            LookupError: Entry not found.
            ValueError: Entry repo not ready.
            PermissionError: User is not the entry owner.
        """
        entry = await self._entry_repo.get_by_id(entry_id)
        if entry is None:
            raise LookupError("Entry not found")

        if entry.repo_status != "ready":
            raise ValueError("Entry repository is not yet ready")

        if entry.created_by != user_id:
            raise PermissionError("Only the entry owner can set tags")

        normalized = normalize_tags(tags)
        return await self._tag_repo.replace_tags(entry_id, normalized, user_id)
