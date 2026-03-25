# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""search tool — full-text search over entries via precomputed tsvectors."""

from phiacta.plugin import PluginManifest, PluginType
from phiacta.tools.search.router import router

manifest = PluginManifest(
    name="search",
    type=PluginType.TOOL,
    version="1.0.0",
    depends_on=["search_tsv", "metadata", "types"],
    description="Full-text search over entries via precomputed tsvectors",
)

__all__ = ["manifest", "router"]
