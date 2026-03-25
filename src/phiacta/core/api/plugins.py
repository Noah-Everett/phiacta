# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Plugin metadata endpoint — returns loaded plugin manifests.

Used by the MCP server to dynamically build instructions from
plugin descriptions without hardcoding extension/view/tool names.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginInfo(BaseModel):
    name: str
    type: str
    version: str
    description: str
    depends_on: list[str]


@router.get("", response_model=list[PluginInfo])
async def list_plugins(request: Request) -> list[PluginInfo]:
    """Return metadata for all loaded plugins. Public read."""
    registry = getattr(request.app.state, "plugin_registry", None)
    if registry is None:
        return []
    return [
        PluginInfo(
            name=m.name,
            type=m.type.value,
            version=m.version,
            description=m.description,
            depends_on=m.depends_on,
        )
        for m in registry.get_manifests()
    ]
