# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FileListItem(BaseModel):
    """A file or directory entry in a repository listing."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    path: str
    type: str
    size: int
