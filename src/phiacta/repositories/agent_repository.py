# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.repositories.base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Agent)

    async def get_by_handle(self, handle: str) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(Agent.handle == handle)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Agent | None:
        result = await self.session.execute(
            select(Agent).where(Agent.email == email)
        )
        return result.scalar_one_or_none()
