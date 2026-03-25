# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Types extension — entry type classification."""

from phiacta.extensions.types.router import router
from phiacta.extensions.types.models import ExtensionType  # noqa: F401
from phiacta.extensions.types.provider import entry_data_provider
from phiacta.plugin import PluginManifest, PluginType

manifest = PluginManifest(
    name="types",
    type=PluginType.EXTENSION,
    version="1.0.0",
    depends_on=[],
    description="Entry type classification",
)

__all__ = ["manifest", "router", "entry_data_provider"]
