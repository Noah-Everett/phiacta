# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, literal_column, select
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
                Interaction.parent_id.is_(None),
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

    async def get_thread(
        self, interaction_id: UUID, *, max_depth: int = 50
    ) -> list[Interaction]:
        t = Interaction.__table__

        # Anchor: the root interaction
        anchor = select(t.c.id, literal_column("0").label("depth")).where(
            t.c.id == interaction_id
        )

        # Recursive CTE
        thread_cte = anchor.cte(name="thread", recursive=True)
        recursive = (
            select(t.c.id, (thread_cte.c.depth + 1).label("depth"))
            .join(thread_cte, t.c.parent_id == thread_cte.c.id)
            .where(thread_cte.c.depth < max_depth, t.c.deleted_at.is_(None))
        )
        thread_cte = thread_cte.union_all(recursive)

        # Join back to ORM model for eager loading
        stmt = (
            select(Interaction)
            .join(thread_cte, Interaction.id == thread_cte.c.id)
            .options(selectinload(Interaction.author))
            .order_by(thread_cte.c.depth, Interaction.created_at)
        )
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

    async def get_with_references(
        self, interaction_id: UUID
    ) -> Interaction | None:
        result = await self.session.execute(
            select(Interaction)
            .where(Interaction.id == interaction_id)
            .options(
                selectinload(Interaction.author),
                selectinload(Interaction.references),
            )
        )
        return result.scalar_one_or_none()

    async def soft_delete(self, interaction: Interaction) -> None:
        interaction.deleted_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def count_replies(self, interaction_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).where(
                Interaction.parent_id == interaction_id,
                Interaction.deleted_at.is_(None),
            )
        )
        return result.scalar_one()
