# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.extensions.compiled_content.models import CompiledOutput


class CompiledContentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        entity_id: UUID,
        format: str,
        data: bytes,
        source_sha: str,
    ) -> CompiledOutput:
        """Insert or update a compiled output for an entry."""
        now = datetime.now(UTC)
        stmt = pg_insert(CompiledOutput).values(
            entity_id=entity_id,
            format=format,
            data=data,
            source_sha=source_sha,
            file_size=len(data),
            compiled_at=now,
            accessed_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_compiled_outputs_entity_format",
            set_={
                "data": stmt.excluded.data,
                "source_sha": stmt.excluded.source_sha,
                "file_size": stmt.excluded.file_size,
                "compiled_at": now,
                "accessed_at": now,
            },
        )
        await self._session.execute(stmt)
        await self._session.flush()

        # Fetch the upserted row
        result = await self._session.execute(
            select(CompiledOutput).where(
                CompiledOutput.entity_id == entity_id,
                CompiledOutput.format == format,
            )
        )
        return result.scalar_one()

    async def get_by_entry(
        self, entity_id: UUID, format: str = "pdf",
    ) -> CompiledOutput | None:
        result = await self._session.execute(
            select(CompiledOutput).where(
                CompiledOutput.entity_id == entity_id,
                CompiledOutput.format == format,
            )
        )
        return result.scalar_one_or_none()

    async def get_metadata_by_entries(
        self, entity_ids: list[UUID],
    ) -> dict[UUID, dict]:
        """Bulk fetch metadata (no data blob) for entry list composition."""
        if not entity_ids:
            return {}
        result = await self._session.execute(
            select(
                CompiledOutput.entity_id,
                CompiledOutput.format,
                CompiledOutput.file_size,
                CompiledOutput.compiled_at,
                CompiledOutput.source_sha,
            ).where(CompiledOutput.entity_id.in_(entity_ids))
        )
        out: dict[UUID, dict] = {}
        for row in result.all():
            out[row.entity_id] = {
                "format": row.format,
                "file_size": row.file_size,
                "compiled_at": row.compiled_at.isoformat(),
                "source_sha": row.source_sha,
            }
        return out

    async def touch_accessed(self, entity_id: UUID, format: str = "pdf") -> None:
        """Update accessed_at timestamp (for LRU eviction)."""
        await self._session.execute(
            update(CompiledOutput)
            .where(
                CompiledOutput.entity_id == entity_id,
                CompiledOutput.format == format,
            )
            .values(accessed_at=datetime.now(UTC))
        )

    async def delete(self, entity_id: UUID, format: str = "pdf") -> None:
        from sqlalchemy import delete as sa_delete

        await self._session.execute(
            sa_delete(CompiledOutput).where(
                CompiledOutput.entity_id == entity_id,
                CompiledOutput.format == format,
            )
        )
