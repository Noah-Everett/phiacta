# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.entry_guards import get_owned_entry, get_writable_entry
from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.schemas.common import PaginatedResponse
from phiacta.core.schemas.entry import (
    EntryCreate, EntryDetailResponse, EntryListItem, EntryResponse, EntryUpdate,
)
from phiacta.core.services.entry_service import EntryService
from phiacta.core.services.git_service import ForgejoError, GitService
from phiacta.core.services.git_service_dep import get_git_service
from phiacta.extensions.metadata.repository import MetadataRepository
from phiacta.extensions.metadata.service import MetadataService
from phiacta.extensions.types.repository import TypeRepository

router = APIRouter(prefix="/entries", tags=["entries"])


def _compose_response(entry, meta=None, ext_type=None) -> dict:
    return {
        "id": entry.id, "schema_version": entry.schema_version,
        "repo_name": entry.repo_name, "forgejo_repo_id": entry.forgejo_repo_id,
        "current_head_sha": entry.current_head_sha, "repo_status": entry.repo_status,
        "status": entry.status, "created_by": entry.created_by,
        "created_at": entry.created_at, "updated_at": entry.updated_at,
        "title": meta.title if meta else None,
        "summary": meta.summary if meta else None,
        "entry_type": ext_type.entry_type if ext_type else None,
    }


@router.get("", response_model=PaginatedResponse[EntryListItem])
async def list_entries(
    status: str = Query("active"), limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EntryListItem]:
    repo = EntryRepository(db)
    repo_status = None if status == "all" else status
    entries = await repo.list_entries(limit=limit, offset=offset, status=repo_status)
    total = await repo.count_entries(status=repo_status)
    entry_ids = [e.id for e in entries]
    meta_map = await MetadataRepository(db).bulk_get_by_entry_ids(entry_ids)
    type_map = await TypeRepository(db).bulk_get_by_entry_ids(entry_ids)
    items = [EntryListItem(**_compose_response(e, meta_map.get(e.id), type_map.get(e.id))) for e in entries]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{entry_id}", response_model=EntryDetailResponse)
async def get_entry(entry_id: UUID, db: AsyncSession = Depends(get_db)) -> EntryDetailResponse:
    entry = await EntryRepository(db).get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    meta = await MetadataRepository(db).get_by_entry_id(entry_id)
    ext_type = await TypeRepository(db).get_by_entry_id(entry_id)
    return EntryDetailResponse(**_compose_response(entry, meta, ext_type))


@router.post("", response_model=EntryResponse, status_code=201)
@limiter.limit("30/minute")
async def create_entry(
    request: Request, body: EntryCreate,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    entry = await EntryService(db).create_entry(body, user)
    meta = await MetadataRepository(db).get_by_entry_id(entry.id)
    ext_type = await TypeRepository(db).get_by_entry_id(entry.id)
    return EntryResponse(**_compose_response(entry, meta, ext_type))


@router.patch("/{entry_id}", response_model=EntryResponse)
@limiter.limit("30/minute")
async def update_entry(
    request: Request, entry_id: UUID, body: EntryUpdate,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    entry = await get_writable_entry(entry_id, user, db)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")
    try:
        await MetadataService(db).update_metadata(entry_id, updates, user.id)
        await db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await db.refresh(entry)
    meta = await MetadataRepository(db).get_by_entry_id(entry_id)
    ext_type = await TypeRepository(db).get_by_entry_id(entry_id)
    return EntryResponse(**_compose_response(entry, meta, ext_type))


@router.post("/{entry_id}/archive", response_model=EntryResponse)
@limiter.limit("10/minute")
async def archive_entry(
    request: Request, entry_id: UUID,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> EntryResponse:
    entry = await get_owned_entry(entry_id, user, db)
    if entry.repo_status != "ready":
        raise HTTPException(status_code=409, detail="Entry repository is not yet ready")
    try:
        entry = await EntryService(db, git_service).archive_entry(entry, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ForgejoError as exc:
        raise HTTPException(status_code=502, detail="Git service unavailable") from exc
    meta = await MetadataRepository(db).get_by_entry_id(entry_id)
    ext_type = await TypeRepository(db).get_by_entry_id(entry_id)
    return EntryResponse(**_compose_response(entry, meta, ext_type))


@router.post("/{entry_id}/unarchive", response_model=EntryResponse)
@limiter.limit("10/minute")
async def unarchive_entry(
    request: Request, entry_id: UUID,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> EntryResponse:
    entry = await get_owned_entry(entry_id, user, db)
    try:
        entry = await EntryService(db, git_service).unarchive_entry(entry, user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ForgejoError as exc:
        raise HTTPException(status_code=502, detail="Git service unavailable") from exc
    meta = await MetadataRepository(db).get_by_entry_id(entry_id)
    ext_type = await TypeRepository(db).get_by_entry_id(entry_id)
    return EntryResponse(**_compose_response(entry, meta, ext_type))
