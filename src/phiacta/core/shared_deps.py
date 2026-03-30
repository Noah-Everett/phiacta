# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Conventional facade for extension plugin dependencies.

Extensions import rate limiting, entry guards, and other shared
dependencies from here rather than reaching into ``core.api``
directly.  This keeps extension code decoupled from the API layer's
internal module paths.

See also ``core.tool_deps`` for the equivalent facade for tool plugins.
"""

from phiacta.core.api.rate_limit import limiter as limiter  # noqa: F401
from phiacta.core.api.entry_guards import get_readable_entry as get_readable_entry  # noqa: F401
from phiacta.core.api.entry_guards import get_writable_entry as get_writable_entry  # noqa: F401
from phiacta.core.api.entry_guards import get_proposable_entry as get_proposable_entry  # noqa: F401
from phiacta.core.api.entry_guards import get_owned_entry as get_owned_entry  # noqa: F401
