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
from phiacta.core.repositories.entry_ref_repository import EntryRefRepository
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.schemas.common import PaginatedResponse
from phiacta.core.schemas.entry import (
    EntryCreate,
    EntryDetailResponse,
    EntryListItem,
    EntryResponse,
    EntryUpdate,
)
from phiacta.core.schemas.entry_ref import EntryRefResponse
from phiacta.core.services.entry_service import EntryService
from phiacta.core.services.git_service import ForgejoError, GitService, RepoNotFoundError
from phiacta.core.services.git_service_dep import get_git_service

router = APIRouter(prefix="/entries", tags=["entries"])

# Max refs returned in the detail endpoint's nested ref lists.
# High enough to be effectively unbounded for normal use; prevents
# pathological memory usage on entries with extreme ref counts.
_DETAIL_REFS_LIMIT = 500


@router.get("", response_model=PaginatedResponse[EntryListItem])
async def list_entries(
    layout_hint: str | None = Query(None),
    status: str = Query("active"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EntryListItem]:
    repo = EntryRepository(db)
    # "all" sentinel bypasses status filter (maps to None in repository)
    repo_status = None if status == "all" else status
    entries = await repo.list_entries(
        limit=limit,
        offset=offset,
        layout_hint=layout_hint,
        status=repo_status,
    )
    total = await repo.count_entries(
        layout_hint=layout_hint, status=repo_status,
    )
    items = [EntryListItem.model_validate(e) for e in entries]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{entry_id}", response_model=EntryDetailResponse)
async def get_entry(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> EntryDetailResponse:
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")

    ref_repo = EntryRefRepository(db)
    outgoing = await ref_repo.list_by_entry(
        entry_id, direction="outgoing", limit=_DETAIL_REFS_LIMIT,
    )
    incoming = await ref_repo.list_by_entry(
        entry_id, direction="incoming", limit=_DETAIL_REFS_LIMIT,
    )

    result = EntryDetailResponse.model_validate(entry)
    result.outgoing_refs = [EntryRefResponse.model_validate(r) for r in outgoing]
    result.incoming_refs = [EntryRefResponse.model_validate(r) for r in incoming]
    return result


@router.post("", response_model=EntryResponse, status_code=201)
@limiter.limit("30/minute")
async def create_entry(
    request: Request,
    body: EntryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    service = EntryService(db)
    entry = await service.create_entry(body, user)
    return EntryResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=EntryResponse)
@limiter.limit("30/minute")
async def update_entry(
    request: Request,
    entry_id: UUID,
    body: EntryUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> EntryResponse:
    """Update entry metadata via git-first write.

    Writes the updated ``.phiacta/entry.yaml`` to git. The DB is updated
    asynchronously by the webhook ingestion pipeline.
    """
    entry = await get_writable_entry(entry_id, user, db)

    service = EntryService(db, git_service)
    try:
        await service.update_entry_metadata(entry, body, user)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Entry repository not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return EntryResponse.model_validate(entry)


@router.post("/{entry_id}/archive", response_model=EntryResponse)
@limiter.limit("10/minute")
async def archive_entry(
    request: Request,
    entry_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> EntryResponse:
    """Archive an entry — makes it read-only, preserving all data."""
    entry = await get_owned_entry(entry_id, user, db)

    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )

    service = EntryService(db, git_service)
    try:
        entry = await service.archive_entry(entry)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return EntryResponse.model_validate(entry)


@router.post("/{entry_id}/unarchive", response_model=EntryResponse)
@limiter.limit("10/minute")
async def unarchive_entry(
    request: Request,
    entry_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> EntryResponse:
    """Unarchive an entry — restores it to active status."""
    entry = await get_owned_entry(entry_id, user, db)

    service = EntryService(db, git_service)
    try:
        entry = await service.unarchive_entry(entry)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return EntryResponse.model_validate(entry)


@router.get("/{entry_id}/references", response_model=list[EntryRefResponse])
async def get_entry_references(
    entry_id: UUID,
    direction: str = Query("both", pattern="^(both|incoming|outgoing)$"),
    db: AsyncSession = Depends(get_db),
) -> list[EntryRefResponse]:
    entry_repo = EntryRepository(db)
    entry = await entry_repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    ref_repo = EntryRefRepository(db)
    refs = await ref_repo.list_by_entry(entry_id, direction=direction)
    return [EntryRefResponse.model_validate(r) for r in refs]
