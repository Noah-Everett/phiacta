# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.personal_access_token import PersonalAccessToken
from phiacta.core.repositories.base import BaseRepository


class PersonalAccessTokenRepository(BaseRepository[PersonalAccessToken]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PersonalAccessToken)

    async def list_by_user(
        self, user_id: UUID, *, include_revoked: bool = True,
    ) -> list[PersonalAccessToken]:
        """List tokens for a user, ordered by creation time."""
        stmt = (
            select(PersonalAccessToken)
            .where(PersonalAccessToken.user_id == user_id)
            .order_by(PersonalAccessToken.created_at.desc())
        )
        if not include_revoked:
            stmt = stmt.where(PersonalAccessToken.revoked_at.is_(None))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_by_prefix(
        self, prefix: str,
    ) -> list[PersonalAccessToken]:
        """Get all non-revoked tokens matching a prefix."""
        result = await self.session.execute(
            select(PersonalAccessToken)
            .where(
                PersonalAccessToken.key_prefix == prefix,
                PersonalAccessToken.revoked_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_id_and_user(
        self, token_id: UUID, user_id: UUID,
    ) -> PersonalAccessToken | None:
        """Get a token by ID, but only if it belongs to the given user."""
        result = await self.session.execute(
            select(PersonalAccessToken).where(
                PersonalAccessToken.id == token_id,
                PersonalAccessToken.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
