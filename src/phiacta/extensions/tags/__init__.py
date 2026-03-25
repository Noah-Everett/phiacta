# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tags extension — user-authored entry classifications.

Provides endpoints for setting, listing, and searching tags on entries.
Tags are community metadata managed via the extension layer, not stored
in the git-derived entries index.
"""

from phiacta.extensions.tags.router import router
from phiacta.extensions.tags.models import ExtensionTag  # noqa: F401 — ensure model registered with Base
from phiacta.extensions.tags.provider import entry_data_provider
from phiacta.plugin import PluginManifest, PluginType

manifest = PluginManifest(
    name="tags",
    type=PluginType.EXTENSION,
    version="1.0.0",
    depends_on=[],
    description="User-authored entry classifications",
)

__all__ = ["manifest", "router", "entry_data_provider"]
