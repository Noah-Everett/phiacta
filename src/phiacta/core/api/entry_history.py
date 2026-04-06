# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry history API (NEV-127).

Public endpoints that proxy commit history and diffs from entry git
repos via the GitService. Both endpoints are read-only and require
no authentication.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.entry_guards import get_readable_entry
from phiacta.core.auth.dependencies import get_optional_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.schemas.entry_history import CommitDiffResponse, CommitListItem
from phiacta.core.pagination import CursorPage, decode_page_cursor, encode_page_cursor
from phiacta.core.services.git_service import ForgejoError, GitService, RepoNotFoundError
from phiacta.core.services.git_service_dep import get_git_service

_FORGEJO_MAX_LIMIT = 50

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("/{entry_id}/history", response_model=CursorPage[CommitListItem])
async def list_entry_commits(
    entry_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> CursorPage[CommitListItem]:
    """List commits for an entry's repository, newest first."""
    await get_readable_entry(entry_id, db, user=user)

    page = 1
    if cursor is not None:
        try:
            page = decode_page_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    effective_limit = min(limit, _FORGEJO_MAX_LIMIT)

    try:
        commits = await git_service.list_commits(
            entry_id, limit=effective_limit, page=page,
        )
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Entry repository not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    items = [CommitListItem.model_validate(c) for c in commits]
    has_more = len(commits) == effective_limit
    next_cursor = encode_page_cursor(page + 1) if has_more else None

    return CursorPage(items=items, limit=effective_limit, has_more=has_more, next_cursor=next_cursor)


@router.get("/{entry_id}/history/{sha}", response_model=CommitDiffResponse)
async def get_entry_commit_diff(
    entry_id: UUID,
    sha: str = Path(..., pattern=r"^[0-9a-f]{40}$"),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> CommitDiffResponse:
    """Get the diff for a specific commit in an entry's repository."""
    await get_readable_entry(entry_id, db, user=user)

    try:
        diff = await git_service.get_diff(entry_id, f"{sha}~1", sha)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Commit not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return CommitDiffResponse.model_validate(diff)
