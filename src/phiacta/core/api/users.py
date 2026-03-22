# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.db.session import get_db
from phiacta.core.repositories.user_repository import UserRepository
from phiacta.core.schemas.auth import PublicUserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}", response_model=PublicUserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> PublicUserResponse:
    repo = UserRepository(db)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return PublicUserResponse.model_validate(user)
