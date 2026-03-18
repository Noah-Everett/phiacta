# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry file read API (NEV-124).

Public endpoints that proxy file reads from entry git repos via the
GitService. Both endpoints are read-only and require no authentication.
"""

from __future__ import annotations

import mimetypes
import urllib.parse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.db.session import get_db
from phiacta.repositories.entry_repository import EntryRepository
from phiacta.schemas.entry_file import FileListItem
from phiacta.services.git_service import ForgejoError, GitService, RepoNotFoundError
from phiacta.services.git_service_dep import get_git_service

router = APIRouter(prefix="/entries", tags=["entries"])


def validate_file_path(path: str) -> None:
    """Validate a file path for safety.

    Raises ``ValueError`` if the path is invalid:
    - Is empty
    - Contains ``..`` segments (path traversal)
    - Starts with ``/`` (absolute path)
    - Targets the ``.phiacta`` directory

    The path is URL-decoded before validation to prevent encoding bypasses.
    """
    if not path:
        raise ValueError("Invalid file path")

    # FastAPI decodes path params once; this second unquote defends against
    # double-encoding attacks (e.g. %252E%252E → %2E%2E → ..).
    normalized = urllib.parse.unquote(path)

    if normalized.startswith("/"):
        raise ValueError("Invalid file path")

    segments = normalized.split("/")

    if ".." in segments:
        raise ValueError("Invalid file path")

    if segments[0] == ".phiacta":
        raise ValueError("File not found")


@router.get("/{entry_id}/files", response_model=list[FileListItem])
async def list_entry_files(
    entry_id: UUID,
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> list[FileListItem]:
    """List files at the root of an entry's repository."""
    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )

    try:
        items = await git_service.list_files(entry_id)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Entry repository not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    filtered = [i for i in items if i.name != ".phiacta"]
    return [FileListItem.model_validate(i) for i in filtered]


@router.get("/{entry_id}/files/{path:path}")
async def get_entry_file_content(
    entry_id: UUID,
    path: str,
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> Response:
    """Get raw file content from an entry's repository."""
    try:
        validate_file_path(path)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail="File not found") from exc
        raise HTTPException(status_code=400, detail="Invalid file path") from exc

    repo = EntryRepository(db)
    entry = await repo.get_by_id(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )

    try:
        content = await git_service.read_file(entry_id, path)
    except RepoNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    content_type, _ = mimetypes.guess_type(path)
    if content_type is None:
        content_type = "application/octet-stream"

    return Response(content=content, media_type=content_type)
