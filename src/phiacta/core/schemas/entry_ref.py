# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EntryRefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    from_entry_id: UUID
    to_entry_id: UUID
    rel: str
    version_sha: str | None
    note: str | None
    created_at: datetime
