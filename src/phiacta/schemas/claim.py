# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ClaimCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    claim_type: str
    namespace_id: UUID
    format: str = Field("markdown", pattern="^(markdown|latex|plain)$")
    content: str = Field(min_length=1, max_length=1_000_000)
    status: str = Field("active", pattern="^(draft|active|archived|retracted)$")
    attrs: dict[str, object] = Field(default_factory=dict)


class ClaimUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    content: str | None = Field(None, min_length=1, max_length=1_000_000)
    format: str | None = Field(None, pattern="^(markdown|latex|plain)$")
    status: str | None = Field(None, pattern="^(draft|active|archived|retracted)$")
    attrs: dict[str, object] | None = None


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    claim_type: str
    format: str
    content_cache: str | None
    namespace_id: UUID
    created_by: UUID
    status: str
    forgejo_repo_id: int | None
    repo_status: str
    cached_confidence: float | None
    confidence_updated_at: datetime | None
    attrs: dict[str, object]
    created_at: datetime
    updated_at: datetime
