# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""latex tool — compile LaTeX source (.tex) to PDF via tectonic."""

from phiacta.plugin import PluginManifest, PluginType
from phiacta.tools.latex.handler import LatexHandler
from phiacta.tools.latex.router import router

manifest = PluginManifest(
    name="latex",
    type=PluginType.TOOL,
    version="1.0.0",
    depends_on=["compiled_content"],
    description="Compile LaTeX source (.tex) to PDF via tectonic",
)

tool_handler = LatexHandler()

__all__ = ["manifest", "router", "tool_handler"]
