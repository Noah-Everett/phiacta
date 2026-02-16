# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.tokens import decode_access_token
from phiacta.db.session import get_db
from phiacta.models.agent import Agent

_bearer_scheme = HTTPBearer()
_bearer_scheme_optional = HTTPBearer(auto_error=False)


async def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    """Require a valid JWT and return the active agent."""
    try:
        agent_id = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if agent is None or not agent.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return agent


async def get_optional_agent(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        _bearer_scheme_optional
    ),
    db: AsyncSession = Depends(get_db),
) -> Agent | None:
    """Optionally authenticate. Returns None if no token is provided."""
    if credentials is None:
        return None

    try:
        agent_id = decode_access_token(credentials.credentials)
    except (jwt.InvalidTokenError, ValueError):
        return None

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if agent is None or not agent.is_active:
        return None

    return agent
