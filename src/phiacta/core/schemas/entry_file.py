# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FileListItem(BaseModel):
    """A file or directory entry in a repository listing."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    path: str
    type: str
    size: int


class FileWriteRequest(BaseModel):
    """Request body for PUT /entries/{entry_id}/files/{path}."""

    content: str = Field(max_length=35_000_000)
    message: str | None = None


class FileDeleteRequest(BaseModel):
    """Optional request body for DELETE /entries/{entry_id}/files/{path}."""

    message: str | None = None


class FileWriteResponse(BaseModel):
    """Response body for file write and delete operations."""

    model_config = ConfigDict(from_attributes=True)

    sha: str
