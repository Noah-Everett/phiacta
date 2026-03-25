# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Metadata extension — title and summary for entries."""

from phiacta.extensions.metadata.router import router
from phiacta.extensions.metadata.models import ExtensionMetadata  # noqa: F401
from phiacta.extensions.metadata.provider import entry_data_provider
from phiacta.plugin import PluginManifest, PluginType

manifest = PluginManifest(
    name="metadata",
    type=PluginType.EXTENSION,
    version="1.0.0",
    depends_on=[],
    description="Entry title and summary",
)

__all__ = ["manifest", "router", "entry_data_provider"]
