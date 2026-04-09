# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Conventional facade for tool plugin dependencies.

Tools import their FastAPI dependencies (DB session, auth) from here
rather than reaching into ``core.db`` or ``core.auth`` directly.  This
keeps tool code decoupled from internal module paths and makes it easy
to swap or extend dependency wiring in one place.
"""

from __future__ import annotations

from phiacta.core.db.session import get_db as get_db  # noqa: F401
from phiacta.core.auth.dependencies import get_optional_user as get_optional_user  # noqa: F401
from phiacta.core.auth.dependencies import get_current_user as get_current_user  # noqa: F401
from phiacta.core.compose import EntryDataProvider as EntryDataProvider  # noqa: F401
from phiacta.core.shared_deps import get_providers as get_providers  # noqa: F401
