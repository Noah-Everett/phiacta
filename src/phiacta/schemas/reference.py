# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from phiacta.schemas.uri import PhiactaURI

_REFERENCE_ROLES = Literal[
    "evidence",
    "rebuts",
    "related",
    "fixes",
    "derives_from",
    "supersedes",
    "citation",
    "corroboration",
    "method",
]


class ReferenceCreate(BaseModel):
    source_uri: PhiactaURI
    target_uri: PhiactaURI
    role: _REFERENCE_ROLES


class ReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_uri: str
    target_uri: str
    role: str
    created_by: UUID
    source_type: str
    target_type: str
    source_claim_id: UUID | None
    target_claim_id: UUID | None
    created_at: datetime
    updated_at: datetime
