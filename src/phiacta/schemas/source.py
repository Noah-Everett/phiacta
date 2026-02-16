# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SourceCreate(BaseModel):
    source_type: str
    title: str | None = None
    external_ref: str | None = None
    content_hash: str | None = None
    attrs: dict[str, object] = {}


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_type: str
    title: str | None
    external_ref: str | None
    content_hash: str | None
    submitted_by: UUID
    submitted_at: datetime
    attrs: dict[str, object]
