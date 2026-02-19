# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator


# ---------------------------------------------------------------------------
# Attrs payload cap (64 KiB serialised)
# ---------------------------------------------------------------------------
_MAX_ATTRS_SIZE = 65_536

_SIGNALS = Literal["agree", "disagree", "neutral"]


def _validate_attrs_size(attrs: dict[str, Any]) -> dict[str, Any]:
    """Enforce 64 KiB cap on serialised attrs."""
    serialized = json.dumps(attrs, default=str)
    if len(serialized) > _MAX_ATTRS_SIZE:
        raise ValueError(
            f"attrs exceeds maximum size of {_MAX_ATTRS_SIZE} characters"
        )
    return attrs


# ---------------------------------------------------------------------------
# Per-kind create schemas (votes + reviews only)
# ---------------------------------------------------------------------------


class VoteCreate(BaseModel):
    kind: Literal["vote"]
    signal: _SIGNALS
    confidence: float = Field(ge=0.0, le=1.0)
    body: None = None
    attrs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sanitise(self) -> VoteCreate:
        self.attrs = _validate_attrs_size(self.attrs)
        return self


class ReviewCreate(BaseModel):
    kind: Literal["review"]
    signal: _SIGNALS
    confidence: float = Field(ge=0.0, le=1.0)
    body: str = Field(min_length=1, max_length=10_000)
    attrs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sanitise(self) -> ReviewCreate:
        self.attrs = _validate_attrs_size(self.attrs)
        return self


# ---------------------------------------------------------------------------
# Discriminated union for POST /interactions
# ---------------------------------------------------------------------------

InteractionCreate = Annotated[
    Annotated[VoteCreate, Tag("vote")]
    | Annotated[ReviewCreate, Tag("review")],
    Discriminator("kind"),
]


# ---------------------------------------------------------------------------
# Body-only update schema (author-only, within 15-minute window)
# ---------------------------------------------------------------------------


class InteractionUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AuthorSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    agent_type: str
    trust_score: float


class InteractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    author: AuthorSummary
    kind: str
    signal: str | None
    confidence: float | None
    weight: float
    body: str | None
    attrs: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class InteractionListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    author: AuthorSummary
    kind: str
    signal: str | None
    confidence: float | None
    weight: float
    body: str | None
    attrs: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
