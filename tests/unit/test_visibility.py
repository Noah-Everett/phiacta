# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for the visibility module.

Tests the visibility helper functions that determine access control
based on entry visibility and requesting user:
- discovery_condition() — SQLAlchemy clause for listing/search queries
- check_entry_access() — raises HTTPException(403) if access denied
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException


class TestCheckEntryAccess:
    """Tests for check_entry_access — the function that guards direct access."""

    def test_public_entry_no_auth_does_not_raise(self) -> None:
        from phiacta.core.visibility import check_entry_access

        entry = MagicMock()
        entry.visibility = "public"
        check_entry_access(entry, user=None)

    def test_public_entry_any_user_does_not_raise(self) -> None:
        from phiacta.core.visibility import check_entry_access

        entry = MagicMock()
        entry.visibility = "public"
        entry.created_by = uuid4()

        user = MagicMock()
        user.id = uuid4()
        check_entry_access(entry, user=user)

    def test_private_entry_owner_does_not_raise(self) -> None:
        from phiacta.core.visibility import check_entry_access

        owner_id = uuid4()
        entry = MagicMock()
        entry.visibility = "private"
        entry.created_by = owner_id

        user = MagicMock()
        user.id = owner_id
        check_entry_access(entry, user=user)

    def test_private_entry_no_auth_raises_403(self) -> None:
        from phiacta.core.visibility import check_entry_access

        entry = MagicMock()
        entry.visibility = "private"
        entry.created_by = uuid4()

        with pytest.raises(HTTPException) as exc_info:
            check_entry_access(entry, user=None)
        assert exc_info.value.status_code == 403

    def test_private_entry_other_user_raises_403(self) -> None:
        from phiacta.core.visibility import check_entry_access

        entry = MagicMock()
        entry.visibility = "private"
        entry.created_by = uuid4()

        user = MagicMock()
        user.id = uuid4()

        with pytest.raises(HTTPException) as exc_info:
            check_entry_access(entry, user=user)
        assert exc_info.value.status_code == 403

    def test_private_entry_403_message_meaningful(self) -> None:
        from phiacta.core.visibility import check_entry_access

        entry = MagicMock()
        entry.visibility = "private"
        entry.created_by = uuid4()

        with pytest.raises(HTTPException) as exc_info:
            check_entry_access(entry, user=None)
        assert exc_info.value.detail


class TestDiscoveryCondition:
    """Tests for discovery_condition — SQLAlchemy WHERE clause for listings/search."""

    def test_no_user_returns_clause(self) -> None:
        from phiacta.core.visibility import discovery_condition
        clause = discovery_condition(user=None)
        assert clause is not None

    def test_with_user_returns_clause(self) -> None:
        from phiacta.core.visibility import discovery_condition
        user = MagicMock()
        user.id = uuid4()
        clause = discovery_condition(user=user)
        assert clause is not None

    def test_no_user_clause_is_different_from_user_clause(self) -> None:
        from phiacta.core.visibility import discovery_condition
        user = MagicMock()
        user.id = uuid4()
        clause_anon = discovery_condition(user=None)
        clause_user = discovery_condition(user=user)
        assert str(clause_anon) != str(clause_user)


class TestVisibilityModuleExports:
    """Verify the visibility module exports the expected functions."""

    def test_exports_check_entry_access(self) -> None:
        from phiacta.core import visibility
        assert hasattr(visibility, "check_entry_access")
        assert callable(visibility.check_entry_access)

    def test_exports_discovery_condition(self) -> None:
        from phiacta.core import visibility
        assert hasattr(visibility, "discovery_condition")
        assert callable(visibility.discovery_condition)
