# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

VALID_VISIBILITY = ("public", "private")


class EntryCreate(BaseModel):
    """Request body for POST /entries.

    Only core fields (content, content_format, visibility) are declared
    explicitly. Extension fields (title, summary, entry_type, tags, ...)
    arrive via ``extra="allow"`` and are dispatched to registered providers.
    """

    model_config = ConfigDict(extra="allow")

    content: str | None = Field(None, max_length=100_000)
    content_format: str = Field("markdown", pattern="^(markdown|latex|plain)$")
    visibility: str = Field("public", pattern="^(public|private)$")


class EntryUpdate(BaseModel):
    """Request body for PATCH /entries/{id}.

    Accepts fields from any writable extension.  Only fields present
    in the request body are routed to the owning provider.
    """

    model_config = ConfigDict(extra="allow")


class EntryListItem(BaseModel):
    """Entry in list responses.  Extension fields pass through dynamically."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: UUID
    repo_name: str
    forgejo_repo_id: int | None = None
    current_head_sha: str | None = None
    repo_status: str
    visibility: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class EntryResponse(BaseModel):
    """Entry response from mutations.  Extension fields pass through dynamically."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: UUID
    repo_name: str
    forgejo_repo_id: int | None = None
    current_head_sha: str | None = None
    repo_status: str
    visibility: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class EntryDetailResponse(EntryResponse):
    """Detail response.  Extension fields pass through dynamically."""

    pass
