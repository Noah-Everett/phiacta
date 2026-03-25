# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EntryCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    content: str | None = Field(None, max_length=100_000)
    content_format: str = Field("markdown", pattern="^(markdown|latex|plain)$")
    entry_type: str | None = None


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
    schema_version: int
    repo_name: str
    forgejo_repo_id: int | None = None
    current_head_sha: str | None = None
    repo_status: str
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class EntryResponse(BaseModel):
    """Entry response from mutations.  Extension fields pass through dynamically."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: UUID
    schema_version: int
    repo_name: str
    forgejo_repo_id: int | None = None
    current_head_sha: str | None = None
    repo_status: str
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class EntryDetailResponse(EntryResponse):
    """Detail response.  Extension fields pass through dynamically."""

    pass
