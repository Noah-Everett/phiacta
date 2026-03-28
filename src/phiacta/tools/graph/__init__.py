# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""graph tool — reference graph traversal over entries."""

from phiacta.plugin import PluginManifest, PluginType
from phiacta.tools.graph.router import router

manifest = PluginManifest(
    name="graph",
    type=PluginType.TOOL,
    version="1.0.0",
    depends_on=["references"],
    description="Reference graph traversal over entries via recursive CTEs",
)

__all__ = ["manifest", "router"]
