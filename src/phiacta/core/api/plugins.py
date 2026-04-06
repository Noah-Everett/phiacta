# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Plugin metadata endpoint — returns loaded plugin manifests.

Used by the MCP server to dynamically build instructions from
plugin descriptions without hardcoding extension/tool names.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from phiacta.core.pagination import CursorPage

router = APIRouter(prefix="/plugins", tags=["plugins"])


class PluginProviderInfo(BaseModel):
    """Entry data provider metadata for an extension plugin."""

    fields: list[str]
    writable_fields: list[str]
    required_on_create: list[str]
    include_in_list: bool
    include_in_detail: bool


class PluginInfo(BaseModel):
    name: str
    type: str
    version: str
    description: str
    depends_on: list[str]
    provider: PluginProviderInfo | None = None


@router.get("", response_model=CursorPage[PluginInfo])
async def list_plugins(request: Request) -> CursorPage[PluginInfo]:
    """Return metadata for all loaded plugins. Bounded — always returns all."""
    registry = getattr(request.app.state, "plugin_registry", None)
    if registry is None:
        return CursorPage(items=[], limit=0, has_more=False, next_cursor=None)

    plugins_map = registry.plugins
    result: list[PluginInfo] = []
    for name, reg in plugins_map.items():
        provider_info = None
        if reg.entry_data_provider is not None:
            p = reg.entry_data_provider
            provider_info = PluginProviderInfo(
                fields=sorted(p.fields),
                writable_fields=sorted(p.writable_fields),
                required_on_create=sorted(p.required_on_create),
                include_in_list=p.include_in_list,
                include_in_detail=p.include_in_detail,
            )
        result.append(PluginInfo(
            name=reg.manifest.name,
            type=reg.manifest.type.value,
            version=reg.manifest.version,
            description=reg.manifest.description,
            depends_on=reg.manifest.depends_on,
            provider=provider_info,
        ))
    return CursorPage(items=result, limit=len(result), has_more=False, next_cursor=None)
