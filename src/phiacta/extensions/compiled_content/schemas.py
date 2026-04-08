# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CompiledContentInfo(BaseModel):
    format: str
    file_size: int
    compiled_at: datetime
    source_sha: str
