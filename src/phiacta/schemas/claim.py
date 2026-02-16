# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ClaimCreate(BaseModel):
    content: str
    claim_type: str
    namespace_id: UUID
    formal_content: str | None = None
    supersedes: UUID | None = None
    status: str = "active"
    attrs: dict[str, object] = {}


class ClaimUpdate(BaseModel):
    content: str | None = None
    status: str | None = None
    formal_content: str | None = None
    attrs: dict[str, object] | None = None


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lineage_id: UUID
    version: int
    content: str
    claim_type: str
    namespace_id: UUID
    created_by: UUID
    formal_content: str | None
    supersedes: UUID | None
    status: str
    attrs: dict[str, object]
    created_at: datetime
    updated_at: datetime
