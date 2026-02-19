# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.claim import Claim
from phiacta.repositories.base import BaseRepository


class ClaimRepository(BaseRepository[Claim]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Claim)

    async def list_claims(
        self,
        limit: int = 50,
        offset: int = 0,
        claim_type: str | None = None,
        namespace_id: UUID | None = None,
        status: str | None = None,
    ) -> list[Claim]:
        stmt = select(Claim)
        if claim_type is not None:
            stmt = stmt.where(Claim.claim_type == claim_type)
        if namespace_id is not None:
            stmt = stmt.where(Claim.namespace_id == namespace_id)
        if status is not None:
            stmt = stmt.where(Claim.status == status)
        stmt = stmt.order_by(Claim.created_at.desc()).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_claims(
        self,
        claim_type: str | None = None,
        namespace_id: UUID | None = None,
        status: str | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Claim)
        if claim_type is not None:
            stmt = stmt.where(Claim.claim_type == claim_type)
        if namespace_id is not None:
            stmt = stmt.where(Claim.namespace_id == namespace_id)
        if status is not None:
            stmt = stmt.where(Claim.status == status)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_repo_status(
        self, claim_id: UUID, *, repo_status: str, forgejo_repo_id: int | None = None,
        current_head_sha: str | None = None,
    ) -> None:
        claim = await self.get_by_id(claim_id)
        if claim is None:
            return
        claim.repo_status = repo_status
        if forgejo_repo_id is not None:
            claim.forgejo_repo_id = forgejo_repo_id
        if current_head_sha is not None:
            claim.current_head_sha = current_head_sha
        await self.session.flush()
