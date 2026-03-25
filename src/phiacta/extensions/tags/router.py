# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tags extension API router.

Endpoints:
- GET  /              List tags for an entry (public)
- PUT  /{entry_id}    Replace all tags on an entry (owner-only)
- GET  /entries        Find entries by tags (public, paginated)

The router is mounted at /v1/extensions/tags/ by the plugin framework.
Route paths here are relative to that prefix.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.schemas.common import PaginatedResponse
from phiacta.extensions.tags.repository import TagRepository
from phiacta.extensions.tags.schemas import (
    EntryTagItem,
    TagListResponse,
    TagResponse,
    TagSetRequest,
)
from phiacta.extensions.tags.service import TagService

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_SEARCH_TAGS = 10


@router.get("/", response_model=TagListResponse)
async def list_tags_for_entry(
    entry_id: UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> TagListResponse:
    """List all tags for a given entry. Public read — no auth required."""
    repo = TagRepository(db)
    tags = await repo.list_by_entry(entry_id)
    return TagListResponse(
        entry_id=entry_id,
        tags=[TagResponse.model_validate(t) for t in tags],
    )


@router.put("/{entry_id}", response_model=TagListResponse)
@limiter.limit("60/minute")
async def set_tags(
    request: Request,
    entry_id: UUID,
    body: TagSetRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TagListResponse:
    """Replace all tags on an entry. Owner-only — requires authentication."""
    service = TagService(db)
    try:
        tags = await service.set_tags(entry_id, body.tags, user.id)
        await db.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Concurrent tag update conflict"
        )

    logger.info("Tags set for entry %s by user %s: %d tags", entry_id, user.id, len(tags))

    return TagListResponse(
        entry_id=entry_id,
        tags=[TagResponse.model_validate(t) for t in tags],
    )


@router.get("/entries", response_model=PaginatedResponse[EntryTagItem])
async def find_entries_by_tags(
    tags: str = Query(..., description="Comma-separated tag names"),
    mode: str = Query("or", pattern="^(and|or)$"),
    include_archived: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[EntryTagItem]:
    """Find entries matching tags. Public read — no auth required.

    OR mode returns entries with ANY matching tag.
    AND mode returns entries with ALL matching tags.
    """
    # Normalize, deduplicate, and filter empty tags from query
    tag_list = list(dict.fromkeys(
        t.strip().lower() for t in tags.split(",") if t.strip()
    ))

    if not tag_list:
        raise HTTPException(
            status_code=422, detail="At least one tag is required"
        )

    if len(tag_list) > _MAX_SEARCH_TAGS:
        raise HTTPException(
            status_code=422,
            detail=f"Maximum {_MAX_SEARCH_TAGS} tags allowed in search query",
        )

    # Map include_archived to status filter (None = no filter)
    repo_status = None if include_archived else "active"

    repo = TagRepository(db)
    entries, total = await repo.find_entries_by_tags(
        tags=tag_list,
        mode=mode,
        limit=limit,
        offset=offset,
        status=repo_status,
    )

    # Bulk-fetch titles from the metadata extension
    from phiacta.extensions.metadata.repository import MetadataRepository
    meta_repo = MetadataRepository(db)
    entry_ids = [e.id for e in entries]
    meta_map = await meta_repo.bulk_get_by_entry_ids(entry_ids)

    items = [
        EntryTagItem(
            entry_id=e.id,
            title=meta_map[e.id].title if e.id in meta_map else "",
        )
        for e in entries
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )
