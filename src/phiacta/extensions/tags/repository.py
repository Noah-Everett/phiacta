# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tag repository — encapsulates queries for the extension_tags table.

Does NOT inherit from BaseRepository because tag operations have different
semantics (replace-all, no updated_at, bulk operations).
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.entry import Entry
from phiacta.extensions.tags.models import ExtensionTag

logger = logging.getLogger(__name__)


class TagRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_entry(self, entry_id: UUID) -> list[ExtensionTag]:
        """List all tags for a given entry, ordered alphabetically.

        entry_id is also the entity_id (shared-PK strategy).
        """
        stmt = (
            select(ExtensionTag)
            .where(ExtensionTag.entity_id == entry_id)
            .order_by(ExtensionTag.tag)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def replace_tags(
        self, entry_id: UUID, tags: list[str], created_by: UUID
    ) -> list[ExtensionTag]:
        """Atomically replace all tags on an entry.

        Deletes all existing tags for the entry, then inserts the new set.
        Returns the newly created ExtensionTag objects.
        """
        # Delete existing tags
        await self.session.execute(
            delete(ExtensionTag).where(ExtensionTag.entity_id == entry_id)
        )

        # Insert new tags
        new_tags: list[ExtensionTag] = []
        for tag in tags:
            ext_tag = ExtensionTag(
                entity_id=entry_id,
                tag=tag,
                created_by=created_by,
            )
            self.session.add(ext_tag)
            new_tags.append(ext_tag)

        await self.session.flush()
        return new_tags

    async def bulk_get_by_entry_ids(
        self, entry_ids: list[UUID],
    ) -> dict[UUID, list[ExtensionTag]]:
        """Bulk-fetch tags grouped by entity_id."""
        if not entry_ids:
            return {}
        stmt = (
            select(ExtensionTag)
            .where(ExtensionTag.entity_id.in_(entry_ids))
            .order_by(ExtensionTag.tag)
        )
        result = await self.session.execute(stmt)
        grouped: dict[UUID, list[ExtensionTag]] = {}
        for tag in result.scalars().all():
            grouped.setdefault(tag.entity_id, []).append(tag)
        return grouped

    async def find_entries_by_tags(
        self,
        tags: list[str],
        mode: str = "or",
        limit: int = 50,
        offset: int = 0,
        status: str | None = "active",
    ) -> tuple[list[Entry], int]:
        """Find entries that match the given tags.

        mode="or": entries with ANY of the specified tags.
        mode="and": entries with ALL of the specified tags.

        status: filter entries by status. None means no filter (all statuses).

        Returns (entries, total_count) for pagination.
        """
        if not tags:
            return [], 0

        if mode == "and":
            subq = (
                select(ExtensionTag.entity_id)
                .where(ExtensionTag.tag.in_(tags))
                .group_by(ExtensionTag.entity_id)
                .having(
                    func.count(func.distinct(ExtensionTag.tag)) == len(tags)
                )
            ).subquery()
        else:
            subq = (
                select(ExtensionTag.entity_id)
                .where(ExtensionTag.tag.in_(tags))
                .distinct()
            ).subquery()

        # Join with entries — works because entry.id == entity.id (shared PK)
        base_query = select(Entry).join(subq, Entry.id == subq.c.entity_id)

        if status is not None:
            base_query = base_query.where(Entry.status == status)

        # Count total
        count_query = select(func.count()).select_from(
            base_query.subquery()
        )
        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        # Get paginated results
        results_query = (
            base_query
            .order_by(Entry.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(results_query)
        entries = list(result.scalars().all())

        return entries, total
