# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content_format: str = Field("markdown", pattern="^(markdown|latex|plain)$")
    layout_hint: str | None = None
    tags: list[str] = Field(default_factory=list)
    summary: str | None = None
    license: str | None = None
    content: str | None = Field(None, max_length=100_000)


class EntryUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    layout_hint: str | None = None
    tags: list[str] | None = None
    summary: str | None = None
    license: str | None = None
    status: str | None = None


class EntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    layout_hint: str | None
    tags: list[str]
    summary: str | None
    license: str | None
    content_format: str
    content_cache: str | None
    schema_version: int
    forgejo_repo_id: int | None
    repo_name: str
    current_head_sha: str | None
    repo_status: str
    status: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime
