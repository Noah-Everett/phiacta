# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    summary: str | None = None
    content: str | None = Field(None, max_length=100_000)
    content_format: str = Field("markdown", pattern="^(markdown|latex|plain)$")
    entry_type: str | None = None


class EntryUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    summary: str | None = None


class EntryListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    title: str | None = None
    summary: str | None = None
    entry_type: str | None = None


class EntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    title: str | None = None
    summary: str | None = None
    entry_type: str | None = None


class EntryDetailResponse(EntryResponse):
    pass
