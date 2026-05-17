# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy.exc import IntegrityError

from phiacta.core.api.entry_guards import (
    get_readable_entry,
    get_writable_entry,
)
from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user, get_optional_user
from phiacta.core.compose import (
    compose_entry_list_responses,
    compose_entry_response,
    parse_field_filter,
)
from phiacta.core.db.session import get_db
from phiacta.core.shared_deps import get_providers
from phiacta.core.models.user import User
from phiacta.core.pagination import (
    CursorPage,
    build_keyset_cursor,
    decode_keyset_cursor,
)
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.models.outbox import Outbox
from phiacta.core.schemas.entry import (
    VALID_VISIBILITY,
    EntryCreate,
    EntryDetailResponse,
    EntryListItem,
    EntryResponse,
    EntryUpdate,
)
from phiacta.core.services.entry_service import EntryService

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get(
    "",
    response_model=CursorPage[EntryListItem],
    summary="List entries",
    description=(
        "Paginated list of entries the caller can read. Use the `include` "
        "query param to choose which extension fields appear on each item "
        "(comma-separated; replaces defaults). Cursor-paginated — pass the "
        "previous response's `next_cursor` to fetch the next page."
    ),
)
@limiter.limit("300/minute")
async def list_entries(
    request: Request,
    visibility: str = Query("all", pattern=r"^(all|public|private)$"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    sort: str = Query("created_at", pattern=r"^(created_at|updated_at)$"),
    order: str = Query("desc", pattern=r"^(asc|desc)$"),
    include: str | None = Query(None),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[EntryListItem]:

    # Decode cursor if provided
    cursor_sort_value: str | None = None
    cursor_id: UUID | None = None
    if cursor is not None:
        try:
            cursor_sort_value, cursor_id = decode_keyset_cursor(cursor, sort, order)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo = EntryRepository(db)
    entries = await repo.list_entries(
        limit=limit,
        visibility=None if visibility == "all" else visibility,
        sort_by=sort, sort_order=order, user=user,
        cursor_sort_value=cursor_sort_value,
        cursor_id=cursor_id,
    )

    # Detect has_more from limit+1 fetch
    has_more = len(entries) > limit
    if has_more:
        entries = entries[:limit]

    providers = get_providers(request)
    inc = parse_field_filter(include)
    composed = await compose_entry_list_responses(
        entries, providers, db, include=inc,
    )
    items = [EntryListItem(**row) for row in composed]

    next_cursor: str | None = None
    if has_more and entries:
        last = entries[-1]
        next_cursor = build_keyset_cursor(
            sort, order, getattr(last, sort), last.id,
        )

    return CursorPage(items=items, limit=limit, has_more=has_more, next_cursor=next_cursor)


@router.get(
    "/{entry_id}",
    response_model=EntryDetailResponse,
    summary="Get a single entry",
    description=(
        "Fetch one entry by ID, including all readable extension fields. "
        "Use the `include` query param to narrow the response to specific "
        "extension fields. Entry content is NOT returned here — read it "
        "from the entry's git repository via the file endpoints."
    ),
)
@limiter.limit("300/minute")
async def get_entry(
    request: Request,
    entry_id: UUID,
    include: str | None = Query(None),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> EntryDetailResponse:
    entry = await get_readable_entry(entry_id, db, user=user)
    providers = get_providers(request)
    inc = parse_field_filter(include)
    composed = await compose_entry_response(
        entry, providers, db, include=inc,
    )
    return EntryDetailResponse(**composed)


@router.post(
    "",
    response_model=EntryResponse,
    status_code=201,
    summary="Create an entry",
    description=(
        "Create a new entry in a single call. Accepts core fields "
        "(`content`, `content_format`, `visibility`) plus any writable "
        "extension fields (e.g. `title`, `summary`, `entry_type`, `tags`). "
        "After this returns, the entry exists but its git repo is being "
        "provisioned asynchronously — watch `repo_status` for `ready`.\n\n"
        "References between entries are NOT created here. After creating "
        "entries that depend on, contain, cite, or contradict each other, "
        "call `create_reference` (POST /v1/extensions/references/{entry_id}) "
        "to wire them up. References are what turn entries into a knowledge "
        "graph — without them, related entries are isolated."
    ),
)
@limiter.limit("30/minute")
async def create_entry(
    request: Request, body: EntryCreate,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    providers = get_providers(request)
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


@router.patch(
    "/{entry_id}",
    response_model=EntryResponse,
    summary="Update entry metadata",
    description=(
        "Patch entry metadata fields (e.g. `title`, `summary`, `entry_type`, "
        "`tags`, `visibility`). Only the fields you include are changed. "
        "Unknown extension fields are silently ignored for plugin forward-"
        "compatibility.\n\n"
        "**Cannot update `content` or `content_format` here.** Content lives "
        "in the entry's git repository. To change it:\n"
        "- **Owner**: write the file directly with "
        "`PUT /v1/entries/{id}/files/.phiacta/content.md` (MCP tool: "
        "`put_entry_file`).\n"
        "- **Non-owner**: propose an edit with "
        "`POST /v1/entries/{id}/edits` (MCP tool: `create_edit_proposal`) — "
        "the owner reviews and merges.\n\n"
        "Sending `content` to this endpoint returns 422 with a pointer to "
        "both routes."
    ),
)
@limiter.limit("30/minute")
async def update_entry(
    request: Request, entry_id: UUID, body: EntryUpdate,
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
) -> EntryResponse:
    entry = await get_writable_entry(entry_id, user, db)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    # Handle visibility change (core field, not routed to providers)
    if "visibility" in updates:
        vis = updates.pop("visibility")
        if vis not in VALID_VISIBILITY:
            raise HTTPException(status_code=422, detail="visibility must be 'public' or 'private'")
        entry.visibility = vis

    providers = get_providers(request)
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

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Concurrent update conflict")
    await db.refresh(entry)
    composed = await compose_entry_response(entry, providers, db)
    return EntryResponse(**composed)
