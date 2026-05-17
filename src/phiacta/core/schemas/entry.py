# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from phiacta.formats import FORMAT_EXTENSIONS

VALID_VISIBILITY = ("public", "private")


class EntryCreate(BaseModel):
    """Request body for POST /entries.

    Only core fields (content, content_format, visibility) are declared
    explicitly. Extension fields (title, summary, entry_type, tags, ...)
    arrive via ``extra="allow"`` and are dispatched to registered providers.
    """

    model_config = ConfigDict(extra="allow")

    content: str | None = Field(None, max_length=100_000)
    content_format: str = Field("markdown")
    visibility: str = Field("public", pattern="^(public|private)$")

    @field_validator("content_format")
    @classmethod
    def _validate_content_format(cls, v: str) -> str:
        if v not in FORMAT_EXTENSIONS:
            raise ValueError(
                f"content_format must be one of {set(FORMAT_EXTENSIONS)}"
            )
        return v


class EntryUpdate(BaseModel):
    """Request body for PATCH /entries/{id}.

    Accepts fields from any writable extension. Only fields present in the
    request body are routed to the owning provider. Unknown extras are
    silently ignored for plugin forward-compatibility.

    Two fields are explicitly rejected because they look updatable but are
    not: ``content`` (use the edit-proposal flow) and ``content_format``
    (immutable after create — it pins the git file extension). Failing
    loud on these prevents silent data loss when an agent assumes PATCH
    accepts the same fields as POST.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _reject_known_immutable_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if "content" in data:
            raise ValueError(
                "Field 'content' cannot be updated via PATCH /v1/entries/{id}. "
                "Entry content lives in the entry's git repository and is "
                "changed through the edit-proposal workflow: "
                "POST /v1/entries/{id}/edits with the new file contents. "
                "This preserves history, attribution, and review.",
            )
        if "content_format" in data:
            raise ValueError(
                "Field 'content_format' is immutable after entry creation. "
                "It pins the file extension of the content file in the "
                "entry's git repository and cannot change without "
                "rewriting history.",
            )
        return data


class EntryListItem(BaseModel):
    """Entry in list responses.  Extension fields pass through dynamically."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: UUID
    repo_name: str
    forgejo_repo_id: int | None = None
    current_head_sha: str | None = None
    repo_status: str
    visibility: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class EntryResponse(BaseModel):
    """Entry response from mutations.  Extension fields pass through dynamically."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    id: UUID
    repo_name: str
    forgejo_repo_id: int | None = None
    current_head_sha: str | None = None
    repo_status: str
    visibility: str
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class EntryDetailResponse(EntryResponse):
    """Detail response.  Extension fields pass through dynamically."""

    pass
