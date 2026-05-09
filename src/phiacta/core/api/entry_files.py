# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry file API (NEV-124, NEV-125).

Public read endpoints and authenticated write endpoints that proxy file
operations on entry git repos via the GitService.
"""

from __future__ import annotations

import mimetypes
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.entry_guards import get_readable_entry, get_writable_entry
from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user, get_optional_user
from phiacta.config import Settings, get_settings
from phiacta.core.db.session import get_db
from phiacta.core.pagination import CursorPage
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

    Reject any path that contains ``%`` outright. Forgejo URL-decodes
    paths once when handling commit/diff payloads, so a path like
    ``..%252Fevil.txt`` would survive a single ``unquote()`` here
    (decoding to ``..%2Fevil.txt`` — one segment, no literal ``..``)
    and then be decoded a second time downstream into ``../evil.txt``,
    escaping the entry's directory. Filesystem paths sent to this
    endpoint as JSON strings never need URL-escapes — spaces and
    other special characters are valid bytes in a path — so rejecting
    ``%`` is both safe and the simplest defensive posture.

    Returns normalized path segments.
    """
    if not path:
        raise ValueError("Invalid file path")
    if "%" in path:
        raise ValueError("Invalid file path")
    if path.startswith("/"):
        raise ValueError("Invalid file path")
    segments = path.split("/")
    if ".." in segments:
        raise ValueError("Invalid file path")
    return segments


def validate_file_path(path: str) -> None:
    """Validate a file path for write/delete operations.

    Only blocks traversal attacks. All paths including ``.phiacta/``
    are writable (entry.yaml is no longer generated or used).
    """
    _validate_path_common(path)


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
        raise HTTPException(status_code=422, detail="Invalid file path") from exc


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


@router.get("/{entry_id}/files", response_model=CursorPage[FileListItem])
@limiter.limit("300/minute")
async def list_entry_files(
    request: Request,
    entry_id: UUID,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> CursorPage[FileListItem]:
    """List files at the root of an entry's repository. Bounded — always returns all files."""
    await get_readable_entry(entry_id, db, user=user)

    try:
        raw_items = await git_service.list_files(entry_id)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Entry repository not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    items = [FileListItem.model_validate(i) for i in raw_items]
    return CursorPage(items=items, limit=len(items), has_more=False, next_cursor=None)


@router.get("/{entry_id}/files/{path:path}")
@limiter.limit("300/minute")
async def get_entry_file_content(
    request: Request,
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
        raise HTTPException(status_code=422, detail="Invalid file path") from exc

    await get_readable_entry(entry_id, db, user=user)

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


@router.post(
    "/{entry_id}/files",
    response_model=FileWriteResponse,
)
@limiter.limit("30/minute")
async def post_entry_files(
    request: Request,
    entry_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
    settings: Settings = Depends(get_settings),
) -> FileWriteResponse:
    """Upload multiple files in a single atomic commit.

    Accepts parallel ``files`` and ``paths`` form fields.  Each file is
    committed to the corresponding path in one git commit.

    Parses the multipart form manually to raise Starlette's default
    ``max_files=1000`` / ``max_fields=1000`` / ``max_part_size=1MB``
    limits.
    """
    form = await request.form(
        max_files=settings.max_upload_files,
        max_fields=settings.max_upload_files,
        max_part_size=settings.max_file_size_bytes,
    )
    files: list[UploadFile] = form.getlist("files")  # type: ignore[assignment]
    paths: list[str] = form.getlist("paths")  # type: ignore[assignment]
    message: str | None = form.get("message")  # type: ignore[assignment]

    if len(files) != len(paths):
        raise HTTPException(
            status_code=422,
            detail=f"Mismatch: {len(files)} files but {len(paths)} paths",
        )
    if len(files) == 0:
        raise HTTPException(status_code=422, detail="No files provided")

    await _get_writable_entry(entry_id, user, db)

    file_contents: list[FileContent] = []
    total_size = 0
    for upload, path in zip(files, paths):
        try:
            validate_file_path(path)
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"Invalid file path: {path}",
            )

        data = await upload.read()
        if len(data) > settings.max_file_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File {path} exceeds maximum size of {settings.max_file_size_bytes} bytes",
            )
        total_size += len(data)
        if total_size > settings.max_upload_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Total upload size exceeds maximum of {settings.max_upload_size_bytes} bytes",
            )
        file_contents.append(FileContent(path=path, content=data))

    # Check repo size limit
    try:
        repo_size = await git_service.get_repo_size(entry_id)
        if repo_size + total_size > settings.max_repo_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Upload would exceed repository size limit of {settings.max_repo_size_bytes} bytes",
            )
    except RepoNotFoundError:
        pass  # new repo, no size to check

    commit_message = message or f"Upload {len(file_contents)} file(s)"
    author = AuthorInfo(name=user.username, email=f"{user.id}@phiacta.local")

    try:
        sha = await git_service.commit_files(
            entry_id, file_contents, author, commit_message,
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

    # Check repo size limit
    try:
        repo_size = await git_service.get_repo_size(entry_id)
        if repo_size + len(data) > settings.max_repo_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"Upload would exceed repository size limit of {settings.max_repo_size_bytes} bytes",
            )
    except RepoNotFoundError:
        pass

    commit_message = message or f"Update {path}"
    author = AuthorInfo(name=user.username, email=f"{user.id}@phiacta.local")

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
    author = AuthorInfo(name=user.username, email=f"{user.id}@phiacta.local")

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
