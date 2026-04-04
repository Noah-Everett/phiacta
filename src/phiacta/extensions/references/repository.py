# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""References repository — queries for the extension_references table."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.pagination import keyset_condition
from phiacta.extensions.references.models import ExtensionReference


class ReferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, ref_id: UUID) -> ExtensionReference | None:
        stmt = select(ExtensionReference).where(ExtensionReference.id == ref_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_entry(
        self, entry_id: UUID, direction: str = "both",
        limit: int = 500,
        cursor_created_at: datetime | None = None,
        cursor_id: UUID | None = None,
        # Legacy offset — unused when cursor is provided
        offset: int = 0,
    ) -> list[ExtensionReference]:
        """List references with keyset pagination. Returns limit+1 for has_more detection."""
        stmt = select(ExtensionReference)
        if direction == "outgoing":
            stmt = stmt.where(ExtensionReference.from_entity_id == entry_id)
        elif direction == "incoming":
            stmt = stmt.where(ExtensionReference.to_entity_id == entry_id)
        else:
            stmt = stmt.where(or_(
                ExtensionReference.from_entity_id == entry_id,
                ExtensionReference.to_entity_id == entry_id,
            ))

        if cursor_created_at is not None and cursor_id is not None:
            stmt = stmt.where(
                keyset_condition(
                    ExtensionReference.created_at, ExtensionReference.id,
                    cursor_created_at, cursor_id, descending=True,
                )
            )

        stmt = stmt.order_by(
            ExtensionReference.created_at.desc(),
            ExtensionReference.id.desc(),
        ).limit(limit + 1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_get_by_entry_ids(
        self, entry_ids: list[UUID], direction: str = "both",
    ) -> dict[UUID, list[ExtensionReference]]:
        """Bulk-fetch references grouped by the queried entity_id."""
        if not entry_ids:
            return {}
        stmt = select(ExtensionReference)
        if direction == "outgoing":
            stmt = stmt.where(ExtensionReference.from_entity_id.in_(entry_ids))
        elif direction == "incoming":
            stmt = stmt.where(ExtensionReference.to_entity_id.in_(entry_ids))
        else:
            stmt = stmt.where(or_(
                ExtensionReference.from_entity_id.in_(entry_ids),
                ExtensionReference.to_entity_id.in_(entry_ids),
            ))
        stmt = stmt.order_by(ExtensionReference.created_at.desc())
        result = await self.session.execute(stmt)
        grouped: dict[UUID, list[ExtensionReference]] = {}
        for ref in result.scalars().all():
            if ref.from_entity_id in entry_ids:
                grouped.setdefault(ref.from_entity_id, []).append(ref)
            if ref.to_entity_id in entry_ids and ref.to_entity_id != ref.from_entity_id:
                grouped.setdefault(ref.to_entity_id, []).append(ref)
        return grouped

    async def create(
        self, from_entry_id: UUID, to_entry_id: UUID, rel: str, created_by: UUID,
        version_sha: str | None = None, note: str | None = None,
    ) -> ExtensionReference:
        ref = ExtensionReference(
            from_entity_id=from_entry_id, to_entity_id=to_entry_id,
            rel=rel[:50], version_sha=version_sha[:40] if version_sha else None,
            note=note, created_by=created_by,
        )
        self.session.add(ref)
        await self.session.flush()
        return ref

    async def delete_by_id(self, ref_id: UUID) -> bool:
        result = await self.session.execute(
            delete(ExtensionReference).where(ExtensionReference.id == ref_id)
        )
        return result.rowcount > 0
