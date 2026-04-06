# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Conventional facade for extension plugin dependencies.

Extensions import rate limiting, entry guards, and other shared
dependencies from here rather than reaching into ``core.api``
directly.  This keeps extension code decoupled from the API layer's
internal module paths.

See also ``core.tool_deps`` for the equivalent facade for tool plugins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from phiacta.core.api.rate_limit import limiter as limiter  # noqa: F401
from phiacta.core.api.entry_guards import get_readable_entry as get_readable_entry  # noqa: F401
from phiacta.core.api.entry_guards import get_writable_entry as get_writable_entry  # noqa: F401
from phiacta.core.api.entry_guards import get_proposable_entry as get_proposable_entry  # noqa: F401
from phiacta.core.api.entry_guards import get_owned_entry as get_owned_entry  # noqa: F401
from phiacta.core.compose import EntryDataProvider

if TYPE_CHECKING:
    from fastapi import Request


def get_providers(request: Request) -> list[EntryDataProvider]:
    """Read registered entry data providers from the plugin registry.

    Shared helper used by core API routers and tool routers.
    """
    registry = getattr(request.app.state, "plugin_registry", None)
    if registry is not None:
        return registry.get_entry_data_providers()
    return getattr(request.app.state, "entry_data_providers", [])
