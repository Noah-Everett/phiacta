# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.entry_guards import get_owned_entry, get_writable_entry
from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user
from phiacta.core.compose import (
    EntryDataProvider,
    compose_entry_list_responses,
    compose_entry_response,
    parse_field_filter,
)
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.schemas.common import PaginatedResponse
from phiacta.core.models.outbox import Outbox
from phiacta.core.schemas.entry import (
    EntryCreate,
    EntryDetailResponse,
    EntryListItem,
    EntryResponse,
    EntryUpdate,
)
from phiacta.core.services.entry_service import EntryService
from phiacta.core.services.git_service import ForgejoError, GitService
from phiacta.core.services.git_service_dep import get_git_service

router = APIRouter(prefix="/entries", tags=["entries"])


def _get_providers(request: Request) -> list[EntryDataProvider]:
    """Read registered entry data providers from the plugin registry.

    Falls back to ``app.state.entry_data_providers`` if the full plugin
    registry isn't available (e.g. in tests that bypass the app lifespan).
    """
    registry = getattr(request.app.state, "plugin_registry", None)
    if registry is not None:
        return registry.get_entry_data_providers()
    return getattr(request.app.state, "entry_data_providers", [])


@router.get("", response_model=PaginatedResponse[EntryListItem])
async def list_entries(
    request: Request,
    status: str = Query("active"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("created_at", pattern=r"^(created_at|updated_at)$"),
    order: str = Query("desc", pattern=r"^(asc|desc)$"),
    include: str | None = Query(None),
    exclude: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EntryListItem]:
    if include is not None and exclude is not None:
        raise HTTPException(
            status_code=422, detail="Cannot specify both include and exclude",
        )
    repo = EntryRepository(db)
    repo_status = None if status == "all" else status
    entries = await repo.list_entries(
        limit=limit, offset=offset, status=repo_status,
        sort_by=sort, sort_order=order,
    )
    total = await repo.count_entries(status=repo_status)
    providers = _get_providers(request)
    inc = parse_field_filter(include)
    exc = parse_field_filter(exclude)
    composed = await compose_entry_list_responses(
        entries, providers, db, include=inc, exclude=exc,
    )
    items = [EntryListItem(**row) for row in composed]
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{entry_id}", response_model=EntryDetailResponse)
async def get_entry(
    request: Request,
    entry_id: UUID,
    include: str | None = Query(None),
    exclude: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> EntryDetailResponse:
    if include is not None and exclude is not None:
        raise HTTPException(
            status_code=422, detail="Cannot specify both include and exclude",
        )
    entry = await EntryRepository(db).get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    providers = _get_providers(request)
    inc = parse_field_filter(include)
    exc = parse_field_filter(exclude)
    composed = await compose_entry_response(
        entry, providers, db, include=inc, exclude=exc,
    )
    return EntryDetailResponse(**composed)


@router.post("", response_model=EntryResponse, status_code=201)
@limiter.limit("30/minute")
async def create_entry(
    request: Request, body: EntryCreate,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    providers = _get_providers(request)
    # Extract provider-destined fields: everything except declared core fields.
    all_fields = body.model_dump(exclude_unset=True)
    core_fields = set(EntryCreate.model_fields)
    provider_fields = {k: v for k, v in all_fields.items() if k not in core_fields}
    try:
        entry = await EntryService(db).create_entry(
            body, user, providers=providers, provider_fields=provider_fields,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    composed = await compose_entry_response(entry, providers, db)
    return EntryResponse(**composed)


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

    providers = _get_providers(request)
    # Route each field to its owning provider.
    for provider in providers:
        if not provider.writable_fields:
            continue
        provider_data = {
            k: v for k, v in updates.items()
            if k in provider.writable_fields
        }
        if provider_data:
            try:
                await provider.write(entry_id, provider_data, user.id, db)
            except LookupError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Enqueue async view recomputation (search tsvector, etc.)
    if entry.repo_status == "ready" and entry.current_head_sha is not None:
        db.add(Outbox(
            aggregate_id=entry_id,
            aggregate_type="entry",
            operation="recompute_views",
            payload={"entry_id": str(entry_id)},
        ))

    await db.commit()
    await db.refresh(entry)
    composed = await compose_entry_response(entry, providers, db)
    return EntryResponse(**composed)


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
    providers = _get_providers(request)
    composed = await compose_entry_response(entry, providers, db)
    return EntryResponse(**composed)


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
    providers = _get_providers(request)
    composed = await compose_entry_response(entry, providers, db)
    return EntryResponse(**composed)
