# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NamespaceCreate(BaseModel):
    name: str
    parent_id: UUID | None = None
    description: str | None = None
    attrs: dict[str, object] = {}


class NamespaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    parent_id: UUID | None
    description: str | None
    attrs: dict[str, object]
    created_at: datetime
    updated_at: datetime
