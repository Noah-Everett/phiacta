# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""References extension API router."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.shared_deps import get_readable_entry, limiter
from phiacta.core.auth.dependencies import get_current_user, get_optional_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.schemas.common import PaginatedResponse
from phiacta.extensions.references.repository import ReferenceRepository
from phiacta.extensions.references.schemas import ReferenceCreateRequest, ReferenceResponse
from phiacta.extensions.references.service import ReferenceService

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_response(ref) -> ReferenceResponse:
    return ReferenceResponse(
        id=ref.id, from_entry_id=ref.from_entity_id, to_entry_id=ref.to_entity_id,
        rel=ref.rel, version_sha=ref.version_sha, note=ref.note,
        created_by=ref.created_by, created_at=ref.created_at,
    )


@router.get("/", response_model=PaginatedResponse[ReferenceResponse])
async def list_references(
    entry_id: UUID = Query(...),
    direction: str = Query("both", pattern="^(both|incoming|outgoing)$"),
    limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ReferenceResponse]:
    await get_readable_entry(entry_id, db, user=user)
    repo = ReferenceRepository(db)
    refs = await repo.list_by_entry(entry_id, direction=direction, limit=limit, offset=offset)
    total = await repo.count_by_entry(entry_id, direction=direction)
    return PaginatedResponse(items=[_to_response(r) for r in refs], total=total, limit=limit, offset=offset)


@router.post("/{entry_id}", response_model=ReferenceResponse, status_code=201)
@limiter.limit("60/minute")
async def create_reference(
    request: Request, entry_id: UUID, body: ReferenceCreateRequest,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> ReferenceResponse:
    service = ReferenceService(db)
    try:
        ref = await service.create_reference(
            entry_id, body.target_entry_id, body.rel, user.id, body.version_sha, body.note,
        )
        await db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Reference already exists (duplicate from/to/rel)")
    return _to_response(ref)


@router.delete("/{reference_id}", status_code=204)
@limiter.limit("60/minute")
async def delete_reference(
    request: Request, reference_id: UUID,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> Response:
    service = ReferenceService(db)
    try:
        await service.delete_reference(reference_id, user.id)
        await db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(status_code=204)
