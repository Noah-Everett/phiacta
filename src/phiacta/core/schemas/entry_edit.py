# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Schemas for the edit proposals API (NEV-126, NEV-162).

Stub -- implementation pending. All tests should FAIL against this stub.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EditProposalFileChange(BaseModel):
    """A single file change in an edit proposal."""

    path: str = Field(min_length=1, max_length=1000)
    content: str


class EditProposalCreate(BaseModel):
    """Request body for POST /entries/{entry_id}/edits."""

    title: str = Field(max_length=500)
    body: str | None = Field(default=None, max_length=10000)
    files: list[EditProposalFileChange] = Field(min_length=1)


class EditProposalAuthor(BaseModel):
    """Author identity in an edit proposal response."""

    model_config = ConfigDict(from_attributes=True)

    username: str


class EditProposalListItem(BaseModel):
    """A single edit proposal in a list response."""

    model_config = ConfigDict(from_attributes=True)

    number: int
    title: str
    body: str | None
    state: str
    is_draft: bool
    author: EditProposalAuthor
    head_branch: str
    base_branch: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None


class EditProposalFileDiff(BaseModel):
    """A file changed in an edit proposal diff."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    patch: str
    additions: int
    deletions: int


class EditProposalDetail(EditProposalListItem):
    """Full detail for a single edit proposal, including diff."""

    diff: list[EditProposalFileDiff]


class EditProposalMergeResponse(BaseModel):
    """Response body for POST /entries/{entry_id}/edits/{number}/merge."""

    sha: str


class EditProposalCloseResponse(BaseModel):
    """Response body for POST /entries/{entry_id}/edits/{number}/close."""

    detail: str
