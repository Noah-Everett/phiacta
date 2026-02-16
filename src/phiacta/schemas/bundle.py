# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from phiacta.schemas.claim import ClaimCreate, ClaimResponse
from phiacta.schemas.relation import RelationCreate, RelationResponse
from phiacta.schemas.source import SourceCreate, SourceResponse


class BundleSubmit(BaseModel):
    idempotency_key: str
    extension_id: str | None = None
    claims: list[ClaimCreate] = []
    relations: list[RelationCreate] = []
    sources: list[SourceCreate] = []
    attrs: dict[str, object] = {}


class BundleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    idempotency_key: str
    submitted_by: UUID
    extension_id: str | None
    status: str
    claim_count: int
    relation_count: int
    artifact_count: int
    submitted_at: datetime
    attrs: dict[str, object]


class BundleDetailResponse(BundleResponse):
    claims: list[ClaimResponse] = []
    relations: list[RelationResponse] = []
    sources: list[SourceResponse] = []
