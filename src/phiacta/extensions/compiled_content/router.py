# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Serve compiled entry output (PDF) with proper content-type."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.auth.dependencies import get_optional_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.shared_deps import get_readable_entry
from phiacta.extensions.compiled_content.repository import CompiledContentRepository

router = APIRouter()

_MIME = {"pdf": "application/pdf"}


@router.get("/{entry_id}")
async def get_compiled_content(
    entry_id: UUID,
    format: str = "pdf",
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> Response:
    """Serve the compiled output for an entry.

    Returns the raw binary (e.g. PDF) with the appropriate content-type.
    Updates ``accessed_at`` for LRU eviction tracking.
    """
    await get_readable_entry(entry_id, db, user=user)

    repo = CompiledContentRepository(db)
    row = await repo.get_by_entry(entry_id, format)
    if row is None:
        raise HTTPException(status_code=404, detail="No compiled output for this entry")

    # Update access time (fire-and-forget within the same session)
    await repo.touch_accessed(entry_id, format)
    await db.commit()

    mime = _MIME.get(format, "application/octet-stream")
    return Response(
        content=row.data,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="output.{format}"',
            "Cache-Control": "private, no-store",
        },
    )
