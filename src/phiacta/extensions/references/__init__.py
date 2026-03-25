# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""References extension — inter-entry references."""

from phiacta.extensions.references.router import router
from phiacta.extensions.references.models import ExtensionReference  # noqa: F401
from phiacta.extensions.references.provider import entry_data_provider
from phiacta.plugin import PluginManifest, PluginType

manifest = PluginManifest(
    name="references",
    type=PluginType.EXTENSION,
    version="1.0.0",
    depends_on=[],
    description="Inter-entry references",
)

__all__ = ["manifest", "router", "entry_data_provider"]
