# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import logging
from datetime import UTC, datetime

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.auth.pat import (
    extract_pat_prefix,
    hash_pat,
    is_pat,
    verify_pat,
    PAT_KEY_PREFIX_LEN,
    PAT_PREFIX,
)
from phiacta.core.auth.tokens import decode_access_token
from phiacta.core.db.session import get_db
from phiacta.core.models.personal_access_token import PersonalAccessToken
from phiacta.core.models.user import User
from phiacta.core.repositories.pat_repository import PersonalAccessTokenRepository

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer()
_bearer_scheme_optional = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


def _is_expired(expires_at: datetime) -> bool:
    """Check if a token is expired, handling both tz-aware and naive datetimes."""
    now = datetime.now(UTC)
    if expires_at.tzinfo is None:
        # Naive datetime (e.g. from SQLite) — treat as UTC
        return expires_at <= now.replace(tzinfo=None)
    return expires_at <= now


async def _authenticate_pat(
    raw_token: str,
    db: AsyncSession,
) -> User | None:
    """Attempt to authenticate via PAT.  Returns User or None.

    On prefix match but hash mismatch, returns None (for optional auth)
    or the caller raises 401 (for required auth).
    """
    # Malformed: too short to extract prefix
    if len(raw_token) < len(PAT_PREFIX) + PAT_KEY_PREFIX_LEN:
        # Timing safety: compute a dummy hash
        hash_pat(raw_token)
        return None

    prefix = extract_pat_prefix(raw_token)
    repo = PersonalAccessTokenRepository(db)
    candidates = await repo.get_active_by_prefix(prefix)

    if not candidates:
        # Timing safety: still compute hash so the response time is similar
        hash_pat(raw_token)
        return None

    # Verify full hash against each candidate (almost always just one)
    matched_token: PersonalAccessToken | None = None
    for candidate in candidates:
        if verify_pat(raw_token, candidate.key_hash):
            matched_token = candidate
            break

    if matched_token is None:
        logger.warning(
            "PAT prefix matched but hash mismatch (prefix=%s)", prefix,
        )
        return None

    # Check expiration
    if matched_token.expires_at is not None and _is_expired(matched_token.expires_at):
        return None

    # Load user
    result = await db.execute(
        select(User).where(User.id == matched_token.user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        return None

    # Update last_used_at via ORM mutation — persisted when the route
    # handler commits.  For read-only endpoints that never commit, the
    # update is lost, which is acceptable (informational timestamp).
    matched_token.last_used_at = datetime.now(UTC)

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require a valid JWT or PAT and return the active user."""
    raw_token = credentials.credentials

    # --- PAT path ---
    if is_pat(raw_token):
        user = await _authenticate_pat(raw_token, db)
        if user is None:
            raise _UNAUTHORIZED
        return user

    # --- JWT path ---
    try:
        user_id = decode_access_token(raw_token)
    except (jwt.InvalidTokenError, ValueError):
        raise _UNAUTHORIZED

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise _UNAUTHORIZED

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        _bearer_scheme_optional
    ),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Optionally authenticate.  Returns None if no token is provided."""
    if credentials is None:
        return None

    raw_token = credentials.credentials

    # --- PAT path ---
    if is_pat(raw_token):
        return await _authenticate_pat(raw_token, db)

    # --- JWT path ---
    try:
        user_id = decode_access_token(raw_token)
    except (jwt.InvalidTokenError, ValueError):
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user_jwt_only(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require a valid JWT (NOT a PAT).  Used for token management endpoints."""
    raw_token = credentials.credentials

    if is_pat(raw_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token management requires password-based authentication",
        )

    try:
        user_id = decode_access_token(raw_token)
    except (jwt.InvalidTokenError, ValueError):
        raise _UNAUTHORIZED

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise _UNAUTHORIZED

    return user
