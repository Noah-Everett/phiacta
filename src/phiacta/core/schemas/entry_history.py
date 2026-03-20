# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CommitAuthor(BaseModel):
    """Git commit author identity."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    email: str


class CommitListItem(BaseModel):
    """A commit in the entry's history."""

    model_config = ConfigDict(from_attributes=True)

    sha: str
    message: str
    author: CommitAuthor
    timestamp: datetime


class FileDiffItem(BaseModel):
    """A file changed in a commit."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    patch: str
    additions: int
    deletions: int


class CommitDiffResponse(BaseModel):
    """Diff details for a specific commit."""

    model_config = ConfigDict(from_attributes=True)

    base_sha: str
    head_sha: str
    files_changed: list[FileDiffItem]
