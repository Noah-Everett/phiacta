# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""compiled_content extension — stores and serves compiled entry output (PDF)."""

from phiacta.extensions.compiled_content.provider import CompiledContentProvider
from phiacta.extensions.compiled_content.router import router
from phiacta.plugin import PluginManifest, PluginType

manifest = PluginManifest(
    name="compiled_content",
    type=PluginType.EXTENSION,
    version="1.0.0",
    description="Stores and serves compiled entry output (e.g. PDF from LaTeX)",
)

entry_data_provider = CompiledContentProvider()

__all__ = ["manifest", "router", "entry_data_provider"]
