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
from phiacta.core.pagination import CursorPage, build_keyset_cursor, decode_keyset_cursor
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


@router.get(
    "/",
    response_model=CursorPage[ReferenceResponse],
    summary="List references for an entry",
    description=(
        "List the typed, directed edges that connect this entry to others. "
        "Use `direction=outgoing` for entries this one points at, "
        "`direction=incoming` for entries that point at this one, or "
        "`direction=both` (default) for everything."
    ),
)
async def list_references(
    entry_id: UUID = Query(...),
    direction: str = Query("both", pattern="^(both|incoming|outgoing)$"),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[ReferenceResponse]:
    await get_readable_entry(entry_id, db, user=user)

    from datetime import datetime as _dt
    cursor_created_at: _dt | None = None
    cursor_id: UUID | None = None
    if cursor is not None:
        try:
            sort_value, cursor_id = decode_keyset_cursor(cursor, "created_at", "desc")
            cursor_created_at = _dt.fromisoformat(sort_value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo = ReferenceRepository(db)
    refs = await repo.list_by_entry(
        entry_id, direction=direction, limit=limit,
        cursor_created_at=cursor_created_at, cursor_id=cursor_id,
    )

    has_more = len(refs) > limit
    if has_more:
        refs = refs[:limit]

    items = [_to_response(r) for r in refs]
    next_cursor: str | None = None
    if has_more and refs:
        last = refs[-1]
        next_cursor = build_keyset_cursor("created_at", "desc", last.created_at, last.id)

    return CursorPage(items=items, limit=limit, has_more=has_more, next_cursor=next_cursor)


@router.post(
    "/{entry_id}",
    response_model=ReferenceResponse,
    status_code=201,
    summary="Create a reference from one entry to another",
    description=(
        "Create a typed, directed reference: source entry "
        "(path param `entry_id`) → target entry (body field "
        "`target_entry_id`) with relation `rel`. Read as "
        '"source [rel] target" (e.g. "this entry `uses` that definition", '
        '"this paper `contains` this theorem"). Common roles: '
        "`contains`, `extends`, `uses`, `assumes`, `supports`, "
        "`contradicts`, `corrects`, `reviews`, `explains`, `applies` — "
        "but `rel` is an open-ended string, use whatever fits.\n\n"
        "Call this after creating entries that meaningfully relate to "
        "each other. Without references, related entries are isolated "
        "and unsearchable as a graph. See the `references` doc resource "
        "for role semantics and when each fits."
    ),
)
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


@router.delete(
    "/{reference_id}",
    status_code=204,
    summary="Delete a reference",
    description=(
        "Remove a reference edge. Only the user who created the reference "
        "can delete it. Deleting a reference does not affect either entry."
    ),
)
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
