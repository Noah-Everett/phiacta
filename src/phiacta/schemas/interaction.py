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

# ---------------------------------------------------------------------------
# Lifecycle keys that are NEVER client-writable on create.
# These are managed exclusively by action endpoints.
# ---------------------------------------------------------------------------
_LIFECYCLE_ATTRS_KEYS = frozenset(
    {
        "issue_status",
        "suggestion_status",
        "resolved_by",
        "accepted_version_id",
    }
)


def _strip_lifecycle_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Remove lifecycle keys from attrs silently."""
    return {k: v for k, v in attrs.items() if k not in _LIFECYCLE_ATTRS_KEYS}


def _validate_attrs_size(attrs: dict[str, Any]) -> dict[str, Any]:
    """Enforce 64 KiB cap on serialised attrs."""
    serialized = json.dumps(attrs, default=str)
    if len(serialized) > _MAX_ATTRS_SIZE:
        raise ValueError(
            f"attrs exceeds maximum size of {_MAX_ATTRS_SIZE} characters"
        )
    return attrs


# ---------------------------------------------------------------------------
# Reference schemas
# ---------------------------------------------------------------------------

_REF_TYPES = Literal["claim", "source", "artifact"]
_REF_ROLES = Literal[
    "evidence",
    "citation",
    "rebuttal",
    "context",
    "method",
    "corroboration",
    "dataset",
]


class ReferenceCreate(BaseModel):
    ref_type: _REF_TYPES
    ref_id: UUID
    role: _REF_ROLES
    attrs: dict[str, Any] = Field(default_factory=dict)


class ReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ref_type: str
    ref_id: UUID
    role: str
    attrs: dict[str, Any]


# ---------------------------------------------------------------------------
# Signals and kinds (Literal types, not enums)
# ---------------------------------------------------------------------------

_SIGNALS = Literal["agree", "disagree", "neutral"]

_ISSUE_LABELS = Literal[
    "methodology_concern",
    "missing_evidence",
    "reproducibility",
    "scope",
    "citation_needed",
    "factual_error",
]

_ISSUE_SEVERITY = Literal["minor", "major", "critical"]


# ---------------------------------------------------------------------------
# Per-kind create schemas
# ---------------------------------------------------------------------------


class VoteCreate(BaseModel):
    kind: Literal["vote"]
    signal: _SIGNALS
    confidence: float = Field(ge=0.0, le=1.0)
    body: None = None
    parent_id: UUID | None = None
    references: list[ReferenceCreate] = Field(default_factory=list, max_length=50)
    attrs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sanitise(self) -> VoteCreate:
        self.attrs = _validate_attrs_size(_strip_lifecycle_attrs(self.attrs))
        return self


class CommentCreate(BaseModel):
    kind: Literal["comment"]
    body: str = Field(min_length=1, max_length=10_000)
    signal: None = None
    confidence: None = None
    parent_id: UUID | None = None
    references: list[ReferenceCreate] = Field(default_factory=list, max_length=50)
    attrs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sanitise(self) -> CommentCreate:
        self.attrs = _validate_attrs_size(_strip_lifecycle_attrs(self.attrs))
        return self


class ReviewCreate(BaseModel):
    kind: Literal["review"]
    signal: _SIGNALS
    confidence: float = Field(ge=0.0, le=1.0)
    body: str = Field(min_length=1, max_length=10_000)
    parent_id: UUID | None = None
    references: list[ReferenceCreate] = Field(default_factory=list, max_length=50)
    attrs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _sanitise(self) -> ReviewCreate:
        self.attrs = _validate_attrs_size(_strip_lifecycle_attrs(self.attrs))
        return self


class IssueCreate(BaseModel):
    kind: Literal["issue"]
    body: str = Field(min_length=1, max_length=10_000)
    signal: _SIGNALS | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    parent_id: UUID | None = None
    references: list[ReferenceCreate] = Field(default_factory=list, max_length=50)
    attrs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_issue(self) -> IssueCreate:
        # signal and confidence must both be set or both be None
        if (self.signal is None) != (self.confidence is None):
            raise ValueError(
                "signal and confidence must both be provided or both omitted"
            )

        # Strip lifecycle keys first
        self.attrs = _strip_lifecycle_attrs(self.attrs)

        # issue_label is required in attrs
        if "issue_label" not in self.attrs:
            raise ValueError("attrs.issue_label is required for issues")

        # Validate issue_label value
        allowed_labels = {
            "methodology_concern",
            "missing_evidence",
            "reproducibility",
            "scope",
            "citation_needed",
            "factual_error",
        }
        if self.attrs["issue_label"] not in allowed_labels:
            raise ValueError(
                f"attrs.issue_label must be one of: {', '.join(sorted(allowed_labels))}"
            )

        # Validate severity if provided
        if "severity" in self.attrs:
            allowed_severity = {"minor", "major", "critical"}
            if self.attrs["severity"] not in allowed_severity:
                raise ValueError(
                    f"attrs.severity must be one of: {', '.join(sorted(allowed_severity))}"
                )

        self.attrs = _validate_attrs_size(self.attrs)
        return self


class SuggestionCreate(BaseModel):
    kind: Literal["suggestion"]
    body: str = Field(min_length=1, max_length=50_000)
    signal: None = None
    confidence: None = None
    parent_id: UUID | None = None
    references: list[ReferenceCreate] = Field(default_factory=list, max_length=50)
    attrs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_suggestion(self) -> SuggestionCreate:
        # Strip lifecycle keys first
        self.attrs = _strip_lifecycle_attrs(self.attrs)

        # suggested_content is required in attrs
        if "suggested_content" not in self.attrs:
            raise ValueError(
                "attrs.suggested_content is required for suggestions"
            )

        self.attrs = _validate_attrs_size(self.attrs)
        return self


# ---------------------------------------------------------------------------
# Discriminated union for POST /interactions
# ---------------------------------------------------------------------------

InteractionCreate = Annotated[
    Annotated[VoteCreate, Tag("vote")]
    | Annotated[CommentCreate, Tag("comment")]
    | Annotated[ReviewCreate, Tag("review")]
    | Annotated[IssueCreate, Tag("issue")]
    | Annotated[SuggestionCreate, Tag("suggestion")],
    Discriminator("kind"),
]


# ---------------------------------------------------------------------------
# Body-only update schema (author-only, within 15-minute window)
# ---------------------------------------------------------------------------


class InteractionUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=50_000)


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
    """Full interaction detail -- used for single-fetch endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    author: AuthorSummary
    parent_id: UUID | None
    kind: str
    signal: str | None
    confidence: float | None
    weight: float
    body: str | None
    attrs: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    reply_count: int = 0
    references: list[ReferenceResponse] = Field(default_factory=list)


class InteractionListResponse(BaseModel):
    """Lighter interaction for list endpoints -- omits references."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    claim_id: UUID
    author: AuthorSummary
    parent_id: UUID | None
    kind: str
    signal: str | None
    confidence: float | None
    weight: float
    body: str | None
    attrs: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None
    reply_count: int = 0
