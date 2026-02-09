# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newpublishing.models.edge import Edge
from newpublishing.repositories.base import BaseRepository


class EdgeRepository(BaseRepository[Edge]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Edge)

    async def get_edges_for_claim(
        self, claim_id: UUID, direction: str = "both"
    ) -> list[Edge]:
        if direction == "outgoing":
            stmt = select(Edge).where(Edge.source_id == claim_id)
        elif direction == "incoming":
            stmt = select(Edge).where(Edge.target_id == claim_id)
        else:
            stmt = select(Edge).where(
                (Edge.source_id == claim_id) | (Edge.target_id == claim_id)
            )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_edges_by_type(self, edge_type: str) -> list[Edge]:
        result = await self.session.execute(
            select(Edge).where(Edge.edge_type == edge_type)
        )
        return list(result.scalars().all())
