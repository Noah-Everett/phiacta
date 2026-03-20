# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Pydantic schemas for the tags extension.

TagSetRequest validates the PUT body. TagResponse and TagListResponse
format the API responses. EntryTagItem is used in the find-by-tags
paginated response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# Individual tag constraint: 1-200 chars, no commas (comma is query separator)
Tag = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^,]+$")]


class TagSetRequest(BaseModel):
    """Request body for PUT /{entry_id} — replace all tags on an entry."""

    tags: Annotated[list[Tag], Field(max_length=50)]


class TagResponse(BaseModel):
    """A single tag in the response."""

    model_config = ConfigDict(from_attributes=True)

    tag: str
    created_by: UUID
    created_at: datetime


class TagListResponse(BaseModel):
    """Response for GET / and PUT /{entry_id}."""

    entry_id: UUID
    tags: list[TagResponse]


class EntryTagItem(BaseModel):
    """An entry matched by tag search — used in find-by-tags response."""

    entry_id: UUID
    title: str
