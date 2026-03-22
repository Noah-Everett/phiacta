# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Schemas for entry issues API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class IssueCreate(BaseModel):
    """Request body for POST /entries/{entry_id}/issues."""

    title: str = Field(max_length=500)
    body: str | None = Field(default=None, max_length=10000)


class IssueCommentCreate(BaseModel):
    """Request body for POST /entries/{entry_id}/issues/{number}/comments."""

    body: str = Field(min_length=1, max_length=10000)


class IssueAuthor(BaseModel):
    """Author identity in an issue response."""

    model_config = ConfigDict(from_attributes=True)

    handle: str


class IssueListItem(BaseModel):
    """Summary of an issue (list view)."""

    model_config = ConfigDict(from_attributes=True)

    number: int
    title: str
    body: str | None
    state: str
    author: IssueAuthor
    comments_count: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class IssueCommentResponse(BaseModel):
    """A single comment on an issue."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    body: str
    author: IssueAuthor
    created_at: datetime
    updated_at: datetime


class IssueDetail(IssueListItem):
    """Full issue with comments."""

    comments: list[IssueCommentResponse]


class IssueCloseResponse(BaseModel):
    detail: str
