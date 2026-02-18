# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.relation import Relation
from phiacta.repositories.base import BaseRepository


class RelationRepository(BaseRepository[Relation]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Relation)

    async def get_relations_for_claim(
        self, claim_id: UUID, direction: str = "both"
    ) -> list[Relation]:
        if direction == "outgoing":
            stmt = select(Relation).where(Relation.source_id == claim_id)
        elif direction == "incoming":
            stmt = select(Relation).where(Relation.target_id == claim_id)
        else:
            stmt = select(Relation).where(
                (Relation.source_id == claim_id) | (Relation.target_id == claim_id)
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_relations_for_claims(
        self, claim_ids: list[UUID], direction: str = "both"
    ) -> list[Relation]:
        if not claim_ids:
            return []
        if direction == "outgoing":
            stmt = select(Relation).where(Relation.source_id.in_(claim_ids))
        elif direction == "incoming":
            stmt = select(Relation).where(Relation.target_id.in_(claim_ids))
        else:
            stmt = select(Relation).where(
                Relation.source_id.in_(claim_ids) | Relation.target_id.in_(claim_ids)
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_relations_by_type(self, relation_type: str) -> list[Relation]:
        result = await self.session.execute(
            select(Relation).where(Relation.relation_type == relation_type)
        )
        return list(result.scalars().all())
