# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from phiacta.models.interaction import Interaction
from phiacta.repositories.base import BaseRepository


class InteractionRepository(BaseRepository[Interaction]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Interaction)

    async def list_by_claim(
        self,
        claim_id: UUID,
        *,
        kind: str | None = None,
        signal: str | None = None,
        author_id: UUID | None = None,
        sort: str = "newest",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Interaction]:
        stmt = (
            select(Interaction)
            .where(
                Interaction.claim_id == claim_id,
                Interaction.deleted_at.is_(None),
            )
            .options(selectinload(Interaction.author))
        )
        if kind is not None:
            stmt = stmt.where(Interaction.kind == kind)
        if signal is not None:
            stmt = stmt.where(Interaction.signal == signal)
        if author_id is not None:
            stmt = stmt.where(Interaction.author_id == author_id)

        if sort == "oldest":
            stmt = stmt.order_by(Interaction.created_at.asc())
        else:
            stmt = stmt.order_by(Interaction.created_at.desc())

        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_signal_by_agent(
        self, claim_id: UUID, author_id: UUID
    ) -> Interaction | None:
        result = await self.session.execute(
            select(Interaction).where(
                Interaction.claim_id == claim_id,
                Interaction.author_id == author_id,
                Interaction.signal.is_not(None),
                Interaction.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_with_author(
        self, interaction_id: UUID
    ) -> Interaction | None:
        result = await self.session.execute(
            select(Interaction)
            .where(Interaction.id == interaction_id)
            .options(selectinload(Interaction.author))
        )
        return result.scalar_one_or_none()

    async def soft_delete(self, interaction: Interaction) -> None:
        interaction.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def count_by_claim(
        self,
        claim_id: UUID,
        *,
        kind: str | None = None,
        signal: str | None = None,
        author_id: UUID | None = None,
    ) -> int:
        stmt = select(func.count()).where(
            Interaction.claim_id == claim_id,
            Interaction.deleted_at.is_(None),
        )
        if kind is not None:
            stmt = stmt.where(Interaction.kind == kind)
        if signal is not None:
            stmt = stmt.where(Interaction.signal == signal)
        if author_id is not None:
            stmt = stmt.where(Interaction.author_id == author_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()
