# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newpublishing.models.agent import Agent
from newpublishing.repositories.base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Agent)

    async def get_by_external_id(self, external_id: str) -> Agent | None:
        result = await self.session.execute(select(Agent).where(Agent.external_id == external_id))
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Agent | None:
        result = await self.session.execute(select(Agent).where(Agent.name == name))
        return result.scalar_one_or_none()
