# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db
from phiacta.repositories.agent_repository import AgentRepository
from phiacta.schemas.auth import PublicAgentResponse

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/{agent_id}", response_model=PublicAgentResponse)
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> PublicAgentResponse:
    repo = AgentRepository(db)
    agent = await repo.get_by_id(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return PublicAgentResponse.model_validate(agent)
