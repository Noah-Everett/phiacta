# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user, get_current_user_jwt_only
from phiacta.core.auth.passwords import hash_password_async, verify_password_async
from phiacta.core.auth.pat import extract_pat_prefix, generate_pat, hash_pat
from phiacta.core.auth.tokens import create_access_token
from phiacta.core.db.session import get_db
from phiacta.core.models.personal_access_token import PersonalAccessToken
from phiacta.core.models.user import User
from phiacta.core.repositories.pat_repository import PersonalAccessTokenRepository
from phiacta.core.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    TokenCreateRequest,
    TokenCreateResponse,
    TokenListItem,
    UserResponse,
)
from phiacta.core.services.entity_service import EntityService

router = APIRouter(prefix="/auth", tags=["auth"])

# Precomputed dummy hash for timing-safe login failures.
_DUMMY_HASH = "$2b$12$LJ3m4ys3Lk0TSwHvGHsvxu1IZSOF5kPuEwGMaLHiYmGKIbkNpEwHi"

# Maximum number of active (non-revoked) tokens per user.
_MAX_ACTIVE_TOKENS_PER_USER = 50


@router.post("/register", response_model=AuthResponse, status_code=201)
@limiter.limit("10/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    # Check username uniqueness
    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    # 1. Create Entity row first (shared-PK, created_by=NULL for users)
    entity_service = EntityService(db)
    entity = await entity_service.register_entity(
        entity_type="user",
        created_by=None,
    )

    # 2. Create User with the same ID as the entity
    user = User(
        id=entity.id,
        username=body.username,
        password_hash=await hash_password_async(body.password),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )
    await db.refresh(user)

    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()

    if user is None:
        # Timing-safe: still run bcrypt verify against dummy hash
        await verify_password_async(body.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not await verify_password_async(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(user)


# ---------------------------------------------------------------------------
# Personal Access Tokens
# ---------------------------------------------------------------------------


@router.post("/tokens", response_model=TokenCreateResponse, status_code=201)
@limiter.limit("10/minute")
async def create_token(
    request: Request,
    body: TokenCreateRequest,
    user: User = Depends(get_current_user_jwt_only),
    db: AsyncSession = Depends(get_db),
) -> TokenCreateResponse:
    """Create a new personal access token.  Returns the raw token once."""
    repo = PersonalAccessTokenRepository(db)

    # Enforce per-user token limit
    active_tokens = await repo.list_by_user(user.id, include_revoked=False)
    if len(active_tokens) >= _MAX_ACTIVE_TOKENS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Maximum of {_MAX_ACTIVE_TOKENS_PER_USER} active tokens per user",
        )

    raw_token = generate_pat()
    prefix = extract_pat_prefix(raw_token)
    key_hash = hash_pat(raw_token)

    expires_at = None
    if body.expires_in_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)

    pat = PersonalAccessToken(
        user_id=user.id,
        name=body.name,
        key_prefix=prefix,
        key_hash=key_hash,
        expires_at=expires_at,
    )
    await repo.create(pat)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Token name already exists",
        )
    await db.refresh(pat)

    return TokenCreateResponse(
        id=pat.id,
        name=pat.name,
        key_prefix=pat.key_prefix,
        token=raw_token,
        created_at=pat.created_at,
        expires_at=pat.expires_at,
    )


@router.get("/tokens", response_model=list[TokenListItem])
async def list_tokens(
    user: User = Depends(get_current_user_jwt_only),
    db: AsyncSession = Depends(get_db),
) -> list[TokenListItem]:
    """List the current user's personal access tokens."""
    repo = PersonalAccessTokenRepository(db)
    tokens = await repo.list_by_user(user.id)
    return [TokenListItem.model_validate(t) for t in tokens]


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_token(
    token_id: UUID,
    user: User = Depends(get_current_user_jwt_only),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a personal access token (soft-delete)."""
    repo = PersonalAccessTokenRepository(db)
    pat = await repo.get_by_id_and_user(token_id, user.id)
    if pat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Token not found",
        )

    pat.revoked_at = datetime.now(UTC)
    await db.commit()
