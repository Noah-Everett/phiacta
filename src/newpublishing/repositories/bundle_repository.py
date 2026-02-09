# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newpublishing.models.bundle import Bundle
from newpublishing.repositories.base import BaseRepository


class BundleRepository(BaseRepository[Bundle]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Bundle)

    async def get_by_idempotency_key(self, key: str) -> Bundle | None:
        result = await self.session.execute(
            select(Bundle).where(Bundle.idempotency_key == key)
        )
        return result.scalar_one_or_none()
