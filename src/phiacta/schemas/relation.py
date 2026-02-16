# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RelationCreate(BaseModel):
    source_id: UUID
    target_id: UUID
    relation_type: str
    created_by: UUID
    strength: float | None = None
    source_provenance: UUID | None = None
    attrs: dict[str, object] = {}


class RelationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    target_id: UUID
    relation_type: str
    strength: float | None
    created_by: UUID
    source_provenance: UUID | None
    attrs: dict[str, object]
    created_at: datetime
    updated_at: datetime
