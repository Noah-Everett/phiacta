# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.claim import Claim
from phiacta.repositories.base import BaseRepository


class ClaimRepository(BaseRepository[Claim]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Claim)

    async def get_by_lineage(self, lineage_id: UUID) -> list[Claim]:
        result = await self.session.execute(
            select(Claim).where(Claim.lineage_id == lineage_id).order_by(Claim.version.desc())
        )
        return list(result.scalars().all())

    async def get_latest_version(self, lineage_id: UUID) -> Claim | None:
        result = await self.session.execute(
            select(Claim)
            .where(Claim.lineage_id == lineage_id)
            .order_by(Claim.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_claims(
        self,
        limit: int = 50,
        offset: int = 0,
        claim_type: str | None = None,
        namespace_id: UUID | None = None,
    ) -> list[Claim]:
        stmt = select(Claim)
        if claim_type is not None:
            stmt = stmt.where(Claim.claim_type == claim_type)
        if namespace_id is not None:
            stmt = stmt.where(Claim.namespace_id == namespace_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
