# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from phiacta.models.review import Review
from phiacta.repositories.base import BaseRepository


class ReviewRepository(BaseRepository[Review]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Review)

    async def list_by_claim(self, claim_id: UUID) -> list[Review]:
        result = await self.session.execute(
            select(Review)
            .where(Review.claim_id == claim_id)
            .options(selectinload(Review.reviewer))
            .order_by(Review.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_claim_and_reviewer(
        self, claim_id: UUID, reviewer_id: UUID
    ) -> Review | None:
        result = await self.session.execute(
            select(Review).where(
                Review.claim_id == claim_id,
                Review.reviewer_id == reviewer_id,
            )
        )
        return result.scalar_one_or_none()
