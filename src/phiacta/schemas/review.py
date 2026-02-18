# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    verdict: Literal["endorse", "dispute", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)
    comment: str | None = Field(None, max_length=10_000)


class ReviewerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    agent_type: str
    trust_score: float


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    verdict: str
    confidence: float
    comment: str | None
    created_at: datetime
    updated_at: datetime
    reviewer: ReviewerSummary
