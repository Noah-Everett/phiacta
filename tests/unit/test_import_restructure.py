# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for the import restructure (NEV-199).

Verifies that after the repo restructure:
1. All core modules are importable via phiacta.core.X paths
2. Old top-level paths (phiacta.api, phiacta.models, etc.) no longer resolve
3. Root-level modules (phiacta.config, phiacta.formats, phiacta.main,
   phiacta.plugin) remain importable at the top level

These tests define the contract for the module layout change.
"""

from __future__ import annotations

import importlib

import pytest


# ---------------------------------------------------------------------------
# Core modules importable via phiacta.core.X
# ---------------------------------------------------------------------------


class TestCoreModulesImportable:
    """All existing modules that moved under core/ must be importable
    via the new phiacta.core.X path.
    """

    def test_import_core_api(self) -> None:
        """phiacta.core.api is importable."""
        mod = importlib.import_module("phiacta.core.api")
        assert mod is not None

    def test_import_core_auth(self) -> None:
        """phiacta.core.auth is importable."""
        mod = importlib.import_module("phiacta.core.auth")
        assert mod is not None

    def test_import_core_cli(self) -> None:
        """phiacta.core.cli is importable."""
        mod = importlib.import_module("phiacta.core.cli")
        assert mod is not None

    def test_import_core_db(self) -> None:
        """phiacta.core.db is importable."""
        mod = importlib.import_module("phiacta.core.db")
        assert mod is not None

    def test_import_core_models(self) -> None:
        """phiacta.core.models is importable."""
        mod = importlib.import_module("phiacta.core.models")
        assert mod is not None

    def test_import_core_models_base(self) -> None:
        """phiacta.core.models.base is importable and has Base, UUIDMixin."""
        mod = importlib.import_module("phiacta.core.models.base")
        assert hasattr(mod, "Base")
        assert hasattr(mod, "UUIDMixin")
        assert hasattr(mod, "TimestampMixin")

    def test_import_core_models_entry(self) -> None:
        """phiacta.core.models.entry is importable and has Entry."""
        mod = importlib.import_module("phiacta.core.models.entry")
        assert hasattr(mod, "Entry")

    def test_import_core_models_user(self) -> None:
        """phiacta.core.models.user is importable and has User."""
        mod = importlib.import_module("phiacta.core.models.user")
        assert hasattr(mod, "User")

    def test_import_core_models_entry_ref(self) -> None:
        """phiacta.core.models.entry_ref is importable and has EntryRef."""
        mod = importlib.import_module("phiacta.core.models.entry_ref")
        assert hasattr(mod, "EntryRef")

    def test_import_core_models_outbox(self) -> None:
        """phiacta.core.models.outbox is importable and has Outbox."""
        mod = importlib.import_module("phiacta.core.models.outbox")
        assert hasattr(mod, "Outbox")

    def test_import_core_repositories(self) -> None:
        """phiacta.core.repositories is importable."""
        mod = importlib.import_module("phiacta.core.repositories")
        assert mod is not None

    def test_import_core_schemas(self) -> None:
        """phiacta.core.schemas is importable."""
        mod = importlib.import_module("phiacta.core.schemas")
        assert mod is not None

    def test_import_core_services(self) -> None:
        """phiacta.core.services is importable."""
        mod = importlib.import_module("phiacta.core.services")
        assert mod is not None

    def test_import_core_webhooks(self) -> None:
        """phiacta.core.webhooks is importable."""
        mod = importlib.import_module("phiacta.core.webhooks")
        assert mod is not None

    def test_import_core_db_session(self) -> None:
        """phiacta.core.db.session is importable and has get_db."""
        mod = importlib.import_module("phiacta.core.db.session")
        assert hasattr(mod, "get_db")

    def test_import_core_api_rate_limit(self) -> None:
        """phiacta.core.api.rate_limit is importable and has limiter."""
        mod = importlib.import_module("phiacta.core.api.rate_limit")
        assert hasattr(mod, "limiter")

    def test_import_core_services_git_service_dep(self) -> None:
        """phiacta.core.services.git_service_dep is importable and has get_git_service."""
        mod = importlib.import_module("phiacta.core.services.git_service_dep")
        assert hasattr(mod, "get_git_service")


# ---------------------------------------------------------------------------
# Old top-level paths no longer resolve
# ---------------------------------------------------------------------------


class TestOldPathsRemoved:
    """After the restructure, old import paths (phiacta.api, phiacta.models,
    etc.) must raise ModuleNotFoundError. This ensures no stale modules
    linger at the old locations.
    """

    def test_old_phiacta_api_raises(self) -> None:
        """phiacta.api raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.api")

    def test_old_phiacta_auth_raises(self) -> None:
        """phiacta.auth raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.auth")

    def test_old_phiacta_cli_raises(self) -> None:
        """phiacta.cli raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.cli")

    def test_old_phiacta_db_raises(self) -> None:
        """phiacta.db raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.db")

    def test_old_phiacta_models_raises(self) -> None:
        """phiacta.models raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.models")

    def test_old_phiacta_repositories_raises(self) -> None:
        """phiacta.repositories raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.repositories")

    def test_old_phiacta_schemas_raises(self) -> None:
        """phiacta.schemas raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.schemas")

    def test_old_phiacta_services_raises(self) -> None:
        """phiacta.services raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.services")

    def test_old_phiacta_webhooks_raises(self) -> None:
        """phiacta.webhooks raises ModuleNotFoundError."""
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("phiacta.webhooks")


# ---------------------------------------------------------------------------
# Root-level modules still importable
# ---------------------------------------------------------------------------


class TestRootModulesStillImportable:
    """Modules that stay at the phiacta root (not under core/) must
    remain importable.
    """

    def test_import_phiacta_config(self) -> None:
        """phiacta.config is importable and has Settings and get_settings."""
        mod = importlib.import_module("phiacta.config")
        assert hasattr(mod, "Settings")
        assert hasattr(mod, "get_settings")

    def test_import_phiacta_formats(self) -> None:
        """phiacta.formats is importable and has FORMAT_EXTENSIONS."""
        mod = importlib.import_module("phiacta.formats")
        assert hasattr(mod, "FORMAT_EXTENSIONS")

    def test_import_phiacta_main(self) -> None:
        """phiacta.main is importable and has app."""
        mod = importlib.import_module("phiacta.main")
        assert hasattr(mod, "app")

    def test_import_phiacta_plugin(self) -> None:
        """phiacta.plugin is importable and has PluginManifest, PluginType, PluginRegistry."""
        mod = importlib.import_module("phiacta.plugin")
        assert hasattr(mod, "PluginManifest")
        assert hasattr(mod, "PluginType")
        assert hasattr(mod, "PluginRegistry")
