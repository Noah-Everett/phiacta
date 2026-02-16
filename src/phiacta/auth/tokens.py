# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from phiacta.config import get_settings


def create_access_token(agent_id: UUID) -> str:
    """Create a JWT access token for the given agent."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(agent_id),
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


def decode_access_token(token: str) -> UUID:
    """Decode a JWT access token and return the agent UUID.

    Raises jwt.InvalidTokenError on any validation failure.
    """
    settings = get_settings()
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
    return UUID(payload["sub"])
