# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Types extension API router."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_optional_user
from phiacta.core.models.user import User
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.visibility import check_entry_access
from phiacta.core.auth.dependencies import get_current_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.extensions.types.repository import TypeRepository
from phiacta.extensions.types.schemas import TypeResponse, TypeSetRequest
from phiacta.extensions.types.service import TypeService

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(ext_type) -> TypeResponse:
    return TypeResponse(
        entry_id=ext_type.entity_id, entry_type=ext_type.entry_type,
        created_by=ext_type.created_by, created_at=ext_type.created_at,
        updated_at=ext_type.updated_at,
    )


@router.get("/", response_model=TypeResponse)
async def get_type(
    entry_id: UUID = Query(...),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> TypeResponse:
    entry = await EntryRepository(db).get_by_id(entry_id)
    if entry is not None:
        check_entry_access(entry, user)
    repo = TypeRepository(db)
    ext_type = await repo.get_by_entry_id(entry_id)
    if ext_type is None:
        raise HTTPException(status_code=404, detail="Type not found")
    return _to_response(ext_type)


@router.put("/{entry_id}", response_model=TypeResponse)
@limiter.limit("60/minute")
async def set_type(
    request: Request, entry_id: UUID, body: TypeSetRequest,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> TypeResponse:
    service = TypeService(db)
    try:
        ext_type = await service.set_type(entry_id, body.entry_type, user.id)
        await db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Concurrent type update conflict")
    return _to_response(ext_type)
