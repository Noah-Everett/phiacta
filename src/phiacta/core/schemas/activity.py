# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Activity Pydantic schemas for the entity registry feature."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ActivityItem(BaseModel):
    id: UUID
    actor_id: UUID
    action: str
    entity_type: str
    entity_id: UUID
    parent_id: UUID | None
    metadata: dict | None
    created_at: datetime
