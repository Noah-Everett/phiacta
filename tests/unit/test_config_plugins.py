# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for the enabled_plugins setting in Settings (NEV-199).

Tests that the new enabled_plugins field on Settings:
1. Defaults to an empty list
2. Accepts an explicit list of plugin names
3. Can be set via the ENABLED_PLUGINS environment variable
"""

from __future__ import annotations

import pytest

from phiacta.config import Settings

# ---------------------------------------------------------------------------
# Required fields for constructing Settings in tests
# ---------------------------------------------------------------------------

_REQUIRED_SETTINGS = {
    "database_url": "sqlite+aiosqlite:///:memory:",
    "jwt_secret_key": "dev-only-change-me-in-production-32chars!",
}


class TestEnabledPluginsDefault:
    """enabled_plugins defaults to an empty list."""

    def test_default_is_empty_list(self) -> None:
        """When enabled_plugins is not provided, it defaults to []."""
        settings = Settings(**_REQUIRED_SETTINGS)
        assert settings.enabled_plugins == []

    def test_default_is_list_type(self) -> None:
        """The default value is a list, not None or another type."""
        settings = Settings(**_REQUIRED_SETTINGS)
        assert isinstance(settings.enabled_plugins, list)

    def test_default_has_zero_length(self) -> None:
        """The default list has exactly zero elements."""
        settings = Settings(**_REQUIRED_SETTINGS)
        assert len(settings.enabled_plugins) == 0


class TestEnabledPluginsExplicit:
    """enabled_plugins accepts an explicit list of plugin names."""

    def test_single_plugin(self) -> None:
        """A single plugin name in the list."""
        settings = Settings(
            **_REQUIRED_SETTINGS,
            enabled_plugins=["tags"],
        )
        assert settings.enabled_plugins == ["tags"]

    def test_multiple_plugins(self) -> None:
        """Multiple plugin names in the list."""
        settings = Settings(
            **_REQUIRED_SETTINGS,
            enabled_plugins=["tags", "search", "export"],
        )
        assert settings.enabled_plugins == ["tags", "search", "export"]
        assert len(settings.enabled_plugins) == 3

    def test_empty_list_explicit(self) -> None:
        """Explicitly passing an empty list works."""
        settings = Settings(
            **_REQUIRED_SETTINGS,
            enabled_plugins=[],
        )
        assert settings.enabled_plugins == []

    def test_preserves_order(self) -> None:
        """The order of plugins in the list is preserved."""
        plugins = ["search", "tags", "export", "embedding"]
        settings = Settings(
            **_REQUIRED_SETTINGS,
            enabled_plugins=plugins,
        )
        assert settings.enabled_plugins == plugins

    def test_plugin_names_are_strings(self) -> None:
        """Each element in enabled_plugins is a string."""
        settings = Settings(
            **_REQUIRED_SETTINGS,
            enabled_plugins=["tags", "search"],
        )
        for name in settings.enabled_plugins:
            assert isinstance(name, str)


class TestEnabledPluginsFromEnvironment:
    """enabled_plugins can be set via the ENABLED_PLUGINS environment variable."""

    def test_from_env_json_array(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ENABLED_PLUGINS env var as a JSON array populates the setting."""
        monkeypatch.setenv("ENABLED_PLUGINS", '["tags"]')
        # Also set the required fields via env to avoid conflicts
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("JWT_SECRET_KEY", "dev-only-change-me-in-production-32chars!")

        settings = Settings()
        assert "tags" in settings.enabled_plugins

    def test_from_env_multiple_plugins(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ENABLED_PLUGINS with multiple plugins."""
        monkeypatch.setenv("ENABLED_PLUGINS", '["tags", "search"]')
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("JWT_SECRET_KEY", "dev-only-change-me-in-production-32chars!")

        settings = Settings()
        assert settings.enabled_plugins == ["tags", "search"]

    def test_from_env_empty_array(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ENABLED_PLUGINS set to '[]' results in empty list."""
        monkeypatch.setenv("ENABLED_PLUGINS", "[]")
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("JWT_SECRET_KEY", "dev-only-change-me-in-production-32chars!")

        settings = Settings()
        assert settings.enabled_plugins == []

    def test_not_set_in_env_uses_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ENABLED_PLUGINS is not in the environment, the default empty
        list is used.
        """
        monkeypatch.delenv("ENABLED_PLUGINS", raising=False)
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("JWT_SECRET_KEY", "dev-only-change-me-in-production-32chars!")

        settings = Settings()
        assert settings.enabled_plugins == []


class TestEnabledPluginsDoesNotBreakExistingSettings:
    """Adding enabled_plugins must not break the existing Settings behavior."""

    def test_existing_fields_still_work(self) -> None:
        """All existing Settings fields continue to function."""
        settings = Settings(
            **_REQUIRED_SETTINGS,
            environment="test",
            log_level="debug",
            enabled_plugins=["tags"],
        )
        assert settings.database_url == "sqlite+aiosqlite:///:memory:"
        assert settings.jwt_secret_key == "dev-only-change-me-in-production-32chars!"
        assert settings.environment == "test"
        assert settings.log_level == "debug"
        assert settings.enabled_plugins == ["tags"]

    def test_jwt_validation_still_enforced(self) -> None:
        """The jwt_secret_key minimum length validation still works."""
        with pytest.raises(ValueError, match="jwt_secret_key"):
            Settings(
                database_url="sqlite+aiosqlite:///:memory:",
                jwt_secret_key="short",
                enabled_plugins=["tags"],
            )
