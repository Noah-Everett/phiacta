# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Dependencies for tool plugins.

Tools must not import from ``core.db`` or ``core.models`` directly.
This module re-exports the dependencies tools need through a safe path.
"""

from phiacta.core.db.session import get_db as get_db  # noqa: F401
from phiacta.core.auth.dependencies import get_optional_user as get_optional_user  # noqa: F401
from phiacta.core.auth.dependencies import get_current_user as get_current_user  # noqa: F401
from phiacta.core.compose import EntryDataProvider as EntryDataProvider  # noqa: F401
