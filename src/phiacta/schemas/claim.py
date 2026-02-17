# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator


_VERIFICATION_CLAIM_TYPES = {"empirical", "mechanistic", "computational"}


class ClaimCreate(BaseModel):
    content: str
    claim_type: str
    namespace_id: UUID
    formal_content: str | None = None
    supersedes: UUID | None = None
    status: str = "active"
    attrs: dict[str, object] = {}
    verification_code: str | None = None
    verification_runner_type: str | None = None

    @model_validator(mode="after")
    def _flag_verification_required(self) -> ClaimCreate:
        if (
            self.claim_type in _VERIFICATION_CLAIM_TYPES
            and self.verification_code is None
        ):
            self.attrs = {**self.attrs, "verification_required": True}
        return self


class ClaimUpdate(BaseModel):
    content: str | None = None
    status: str | None = None
    formal_content: str | None = None
    attrs: dict[str, object] | None = None


class ClaimVerifyRequest(BaseModel):
    code_content: str
    runner_type: str


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lineage_id: UUID
    version: int
    content: str
    claim_type: str
    namespace_id: UUID
    created_by: UUID
    formal_content: str | None
    supersedes: UUID | None
    status: str
    attrs: dict[str, object]
    created_at: datetime
    updated_at: datetime
    verification_level: str | None = None
    verification_status: str | None = None

    @model_validator(mode="after")
    def _populate_verification_fields(self) -> ClaimResponse:
        if self.verification_level is None:
            self.verification_level = self.attrs.get("verification_level")  # type: ignore[assignment]
        if self.verification_status is None:
            self.verification_status = self.attrs.get("verification_status")  # type: ignore[assignment]
        return self
