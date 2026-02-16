# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.auth.dependencies import get_current_agent
from phiacta.auth.passwords import hash_password, verify_password
from phiacta.auth.tokens import create_access_token
from phiacta.db.session import get_db
from phiacta.models.agent import Agent
from phiacta.schemas.auth import (
    AgentResponse,
    AuthResponse,
    LoginRequest,
    RegisterRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])

limiter = Limiter(key_func=get_remote_address)

# Precomputed dummy hash for timing-safe login failures.
# This is bcrypt hash of a random string, used to burn CPU time
# when the email is not found so the response time is consistent.
_DUMMY_HASH = "$2b$12$LJ3m4ys3Lk0TSwHvGHsvxu1IZSOF5kPuEwGMaLHiYmGKIbkNpEwHi"


@router.post("/register", response_model=AuthResponse, status_code=201)
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    # Check email uniqueness
    result = await db.execute(select(Agent).where(Agent.email == body.email))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    agent = Agent(
        agent_type="human",
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    token = create_access_token(agent.id)
    return AuthResponse(
        access_token=token,
        agent=AgentResponse.model_validate(agent),
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    result = await db.execute(select(Agent).where(Agent.email == body.email))
    agent = result.scalar_one_or_none()

    if agent is None:
        # Timing-safe: still run bcrypt verify against dummy hash
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(body.password, agent.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not agent.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(agent.id)
    return AuthResponse(
        access_token=token,
        agent=AgentResponse.model_validate(agent),
    )


@router.get("/me", response_model=AgentResponse)
async def me(
    agent: Agent = Depends(get_current_agent),
) -> AgentResponse:
    return AgentResponse.model_validate(agent)
