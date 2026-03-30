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

from phiacta.core.api.entry_guards import check_archive_visibility
from phiacta.core.auth.dependencies import get_optional_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.schemas.entry_history import CommitDiffResponse, CommitListItem
from phiacta.core.services.git_service import ForgejoError, GitService, RepoNotFoundError
from phiacta.core.services.git_service_dep import get_git_service

router = APIRouter(prefix="/entries", tags=["entries"])


@router.get("/{entry_id}/history", response_model=list[CommitListItem])
async def list_entry_commits(
    entry_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> list[CommitListItem]:
    """List commits for an entry's repository, newest first."""
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    check_archive_visibility(entry, user)
    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )

    try:
        commits = await git_service.list_commits(
            entry_id, limit=limit, page=page,
        )
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Entry repository not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return [CommitListItem.model_validate(c) for c in commits]


@router.get("/{entry_id}/history/{sha}", response_model=CommitDiffResponse)
async def get_entry_commit_diff(
    entry_id: UUID,
    sha: str = Path(..., pattern=r"^[0-9a-f]{40}$"),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> CommitDiffResponse:
    """Get the diff for a specific commit in an entry's repository."""
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    check_archive_visibility(entry, user)
    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )

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
