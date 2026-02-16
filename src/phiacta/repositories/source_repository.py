# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.source import Source
from phiacta.repositories.base import BaseRepository


class SourceRepository(BaseRepository[Source]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Source)

    async def get_by_external_ref(self, ref: str) -> Source | None:
        result = await self.session.execute(select(Source).where(Source.external_ref == ref))
        return result.scalar_one_or_none()

    async def get_by_content_hash(self, content_hash: str) -> Source | None:
        result = await self.session.execute(
            select(Source).where(Source.content_hash == content_hash)
        )
        return result.scalar_one_or_none()
