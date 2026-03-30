# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Metadata extension API router."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.shared_deps import limiter
from phiacta.core.auth.dependencies import get_current_user, get_optional_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.visibility import check_entry_access
from phiacta.extensions.metadata.repository import MetadataRepository
from phiacta.extensions.metadata.schemas import (
    MetadataResponse, MetadataSetRequest, MetadataUpdateRequest,
)
from phiacta.extensions.metadata.service import MetadataService

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(meta) -> MetadataResponse:
    return MetadataResponse(
        entry_id=meta.entity_id, title=meta.title, summary=meta.summary,
        created_by=meta.created_by, created_at=meta.created_at, updated_at=meta.updated_at,
    )


@router.get("/", response_model=MetadataResponse)
async def get_metadata(
    entry_id: UUID = Query(...),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> MetadataResponse:
    entry = await EntryRepository(db).get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    check_entry_access(entry, user)
    repo = MetadataRepository(db)
    meta = await repo.get_by_entry_id(entry_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Metadata not found")
    return _to_response(meta)


@router.put("/{entry_id}", response_model=MetadataResponse)
@limiter.limit("60/minute")
async def set_metadata(
    request: Request, entry_id: UUID, body: MetadataSetRequest,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MetadataResponse:
    service = MetadataService(db)
    try:
        meta = await service.set_metadata(entry_id, body.title, user.id, summary=body.summary)
        await db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Concurrent metadata update conflict")
    return _to_response(meta)


@router.patch("/{entry_id}", response_model=MetadataResponse)
@limiter.limit("60/minute")
async def update_metadata(
    request: Request, entry_id: UUID, body: MetadataUpdateRequest,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> MetadataResponse:
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    service = MetadataService(db)
    try:
        meta = await service.update_metadata(entry_id, updates, user.id)
        await db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return _to_response(meta)
