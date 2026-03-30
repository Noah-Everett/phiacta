# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry file API (NEV-124, NEV-125).

Public read endpoints and authenticated write endpoints that proxy file
operations on entry git repos via the GitService.
"""

from __future__ import annotations

import mimetypes
import urllib.parse
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.entry_guards import check_archive_visibility, get_writable_entry
from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user, get_optional_user
from phiacta.config import Settings, get_settings
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.schemas.entry_file import (
    FileDeleteRequest,
    FileListItem,
    FileWriteResponse,
)
from phiacta.core.services.git_service import (
    AuthorInfo,
    FileContent,
    ForgejoError,
    GitService,
    RepoNotFoundError,
)
from phiacta.core.services.git_service_dep import get_git_service

router = APIRouter(prefix="/entries", tags=["entries"])


def _validate_path_common(path: str) -> list[str]:
    """Common path validation — traversal and format checks.

    Returns normalized path segments.
    """
    if not path:
        raise ValueError("Invalid file path")
    normalized = urllib.parse.unquote(path)
    if normalized.startswith("/"):
        raise ValueError("Invalid file path")
    segments = normalized.split("/")
    if ".." in segments:
        raise ValueError("Invalid file path")
    return segments


def validate_file_path(path: str) -> None:
    """Validate a file path for write/delete operations.

    Blocks ``.phiacta/entry.yaml`` (identity file, immutable).
    All other paths including ``.phiacta/content.*`` are writable.
    """
    segments = _validate_path_common(path)
    if segments[0] == ".phiacta" and len(segments) >= 2 and segments[1] == "entry.yaml":
        raise ValueError("File not found")


def validate_file_path_read(path: str) -> None:
    """Validate a file path for read operations.

    All paths are readable (including ``.phiacta/entry.yaml``).
    Only blocks traversal attacks.
    """
    _validate_path_common(path)


def _raise_for_invalid_path(path: str) -> None:
    """Validate a file path and raise the appropriate HTTPException."""
    try:
        validate_file_path(path)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail="File not found") from exc
        raise HTTPException(status_code=400, detail="Invalid file path") from exc


async def _get_writable_entry(
    entry_id: UUID,
    user: User,
    db: AsyncSession,
) -> Entry:
    """Convenience wrapper for backwards-compatible call sites."""
    return await get_writable_entry(entry_id, user, db)


# ---------------------------------------------------------------------------
# Read endpoints (NEV-124) — public, no authentication required
# ---------------------------------------------------------------------------


@router.get("/{entry_id}/files", response_model=list[FileListItem])
async def list_entry_files(
    entry_id: UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> list[FileListItem]:
    """List files at the root of an entry's repository."""
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
        items = await git_service.list_files(entry_id)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Entry repository not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return [FileListItem.model_validate(i) for i in items]


@router.get("/{entry_id}/files/{path:path}")
async def get_entry_file_content(
    entry_id: UUID,
    path: str,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> Response:
    """Get raw file content or directory listing from an entry's repository."""
    try:
        validate_file_path_read(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path") from exc

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
        content = await git_service.read_file(entry_id, path)
    except (RepoNotFoundError, AttributeError):
        # RepoNotFoundError: path doesn't exist
        # AttributeError: path is a directory (Forgejo returns a list, not a dict)
        try:
            items = await git_service.list_files(entry_id, path=path)
            return [FileListItem.model_validate(i) for i in items]
        except (RepoNotFoundError, ForgejoError) as exc:
            raise HTTPException(status_code=404, detail="File not found") from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    content_type, _ = mimetypes.guess_type(path)
    if content_type is None:
        content_type = "application/octet-stream"

    return Response(content=content, media_type=content_type)


# ---------------------------------------------------------------------------
# Write endpoints (NEV-125) — require authentication + ownership
# ---------------------------------------------------------------------------


@router.put(
    "/{entry_id}/files/{path:path}",
    response_model=FileWriteResponse,
)
@limiter.limit("60/minute")
async def put_entry_file(
    request: Request,
    entry_id: UUID,
    path: str,
    content: UploadFile = File(...),
    message: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
    settings: Settings = Depends(get_settings),
) -> FileWriteResponse:
    """Create or update a file in an entry's repository."""
    _raise_for_invalid_path(path)

    data = await content.read()

    if len(data) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File content exceeds maximum size of {settings.max_file_size_bytes} bytes",
        )

    await _get_writable_entry(entry_id, user, db)

    commit_message = message or f"Update {path}"
    author = AuthorInfo(name=user.handle, email=f"{user.id}@phiacta.local")

    try:
        sha = await git_service.commit_files(
            entry_id,
            [FileContent(path=path, content=data)],
            author,
            commit_message,
        )
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Entry repository not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return FileWriteResponse(sha=sha)


@router.delete(
    "/{entry_id}/files/{path:path}",
    response_model=FileWriteResponse,
)
@limiter.limit("60/minute")
async def delete_entry_file(
    request: Request,
    entry_id: UUID,
    path: str,
    body: FileDeleteRequest | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> FileWriteResponse:
    """Delete a file from an entry's repository."""
    _raise_for_invalid_path(path)

    await _get_writable_entry(entry_id, user, db)

    message = (body.message if body else None) or f"Delete {path}"
    author = AuthorInfo(name=user.handle, email=f"{user.id}@phiacta.local")

    try:
        sha = await git_service.delete_file(
            entry_id,
            path,
            author,
            message,
        )
    except RepoNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return FileWriteResponse(sha=sha)
