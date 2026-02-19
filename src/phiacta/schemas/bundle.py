# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from phiacta.schemas.claim import ClaimCreate, ClaimResponse
from phiacta.schemas.reference import ReferenceCreate, ReferenceResponse
from phiacta.schemas.source import SourceCreate, SourceResponse


class BundleSubmit(BaseModel):
    idempotency_key: str = Field(max_length=256)
    extension_id: str | None = None
    claims: list[ClaimCreate] = []
    references: list[ReferenceCreate] = []
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
    reference_count: int
    artifact_count: int
    submitted_at: datetime
    attrs: dict[str, object]


class BundleDetailResponse(BundleResponse):
    claims: list[ClaimResponse] = []
    references: list[ReferenceResponse] = []
    sources: list[SourceResponse] = []
