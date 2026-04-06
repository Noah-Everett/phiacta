# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for the tool_deps module.

Verifies that phiacta.core.tool_deps correctly re-exports the
dependencies tools need, and that the exported objects are the same
functions/classes as the canonical originals.
"""

from __future__ import annotations


class TestToolDepsExports:
    """All expected names are importable from tool_deps."""

    def test_get_db_is_available(self) -> None:
        from phiacta.core.tool_deps import get_db  # noqa: F401

    def test_get_optional_user_is_available(self) -> None:
        from phiacta.core.tool_deps import get_optional_user  # noqa: F401

    def test_get_current_user_is_available(self) -> None:
        from phiacta.core.tool_deps import get_current_user  # noqa: F401

    def test_entry_data_provider_is_available(self) -> None:
        from phiacta.core.tool_deps import EntryDataProvider  # noqa: F401


class TestToolDepsIdentity:
    """Re-exported objects are the exact same objects as the originals."""

    def test_get_db_is_same_function(self) -> None:
        from phiacta.core.tool_deps import get_db as td_get_db
        from phiacta.core.db.session import get_db as session_get_db

        assert td_get_db is session_get_db, (
            "tool_deps.get_db should be the exact same function as "
            "core.db.session.get_db"
        )

    def test_get_optional_user_is_same_function(self) -> None:
        from phiacta.core.tool_deps import get_optional_user as td_gou
        from phiacta.core.auth.dependencies import get_optional_user as auth_gou

        assert td_gou is auth_gou, (
            "tool_deps.get_optional_user should be the exact same function as "
            "core.auth.dependencies.get_optional_user"
        )

    def test_get_current_user_is_same_function(self) -> None:
        from phiacta.core.tool_deps import get_current_user as td_gcu
        from phiacta.core.auth.dependencies import get_current_user as auth_gcu

        assert td_gcu is auth_gcu, (
            "tool_deps.get_current_user should be the exact same function as "
            "core.auth.dependencies.get_current_user"
        )

    def test_entry_data_provider_is_same_class(self) -> None:
        from phiacta.core.tool_deps import EntryDataProvider as td_edp
        from phiacta.core.compose import EntryDataProvider as compose_edp

        assert td_edp is compose_edp, (
            "tool_deps.EntryDataProvider should be the exact same class as "
            "core.compose.EntryDataProvider"
        )
