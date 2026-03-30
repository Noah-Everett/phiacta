# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Plugin framework for Phiacta extensions and tools.

Provides the manifest dataclass, plugin type enum, and the registry
that discovers, validates, and mounts plugins at startup.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from collections.abc import Callable, Coroutine

if TYPE_CHECKING:
    from pydantic_settings import BaseSettings

    from phiacta.core.compose import EntryDataProvider

# Type alias for on_ingest hook functions.
# Signature: async def on_ingest(entry_id: UUID, content: str | None, metadata: dict, db: AsyncSession) -> None
OnIngestHook = Callable[..., Coroutine]

logger = logging.getLogger(__name__)


class PluginType(Enum):
    """Type of plugin: extension or tool.

    This is a closed infrastructure set defined by the platform architecture,
    not open-ended domain data. The anti-pattern prohibition on Python enums
    applies to domain values like ``layout_hint`` or reference ``rel`` where
    future values are unknowable.
    """

    EXTENSION = "extension"
    TOOL = "tool"


@dataclass(frozen=True)
class PluginManifest:
    """Metadata for a plugin. Each plugin module exposes a ``manifest`` instance."""

    name: str
    type: PluginType
    version: str
    depends_on: list[str] = field(default_factory=list)
    description: str = ""
    settings_class: type[BaseSettings] | None = None


@dataclass
class PluginRegistration:
    """A discovered plugin ready to be mounted."""

    manifest: PluginManifest
    router: APIRouter | None = None
    # Plugin-specific settings instance; type varies per plugin.
    settings: Any = None
    # Optional data provider for auto-composed entry responses.
    entry_data_provider: EntryDataProvider | None = None
    # Optional hook called during ingestion (content changes, reconciliation).
    on_ingest: OnIngestHook | None = None


# Maps PluginType to the directory name under src/phiacta/
_TYPE_TO_DIR: dict[PluginType, str] = {
    PluginType.EXTENSION: "extensions",
    PluginType.TOOL: "tools",
}

# Maps PluginType to the URL prefix for router mounting
_TYPE_TO_PREFIX: dict[PluginType, str] = {
    PluginType.EXTENSION: "/v1/extensions",
    PluginType.TOOL: "/v1/tools",
}

# Maps plugin_dirs key to PluginType
_DIR_KEY_TO_TYPE: dict[str, PluginType] = {
    "extension": PluginType.EXTENSION,
    "tool": PluginType.TOOL,
}


class PluginRegistry:
    """Discovers, validates, and registers plugins at startup.

    Call :meth:`discover` first, then :meth:`resolve_dependencies`.

    Parameters
    ----------
    plugin_dirs
        Mapping of plugin type key ("extension", "tool") to the
        directory Path containing plugin packages. If ``None``, uses the
        default directories under ``src/phiacta/``.
    enabled_plugins
        List of plugin names to load. Only plugins in this list are loaded.
        An empty list means no plugins.
    """

    def __init__(
        self,
        *,
        plugin_dirs: dict[str, Path] | None = None,
        enabled_plugins: list[str] | None = None,
    ) -> None:
        self._plugins: dict[str, PluginRegistration] = {}
        self._enabled_plugins: list[str] = enabled_plugins or []
        self._use_file_loader = plugin_dirs is not None

        if plugin_dirs is not None:
            self._plugin_dirs = plugin_dirs
        else:
            package_root = Path(__file__).parent
            self._plugin_dirs = {
                "extension": package_root / "extensions",
                "tool": package_root / "tools",
            }

    @property
    def plugins(self) -> dict[str, PluginRegistration]:
        """Registered plugins, keyed by name."""
        return dict(self._plugins)

    def discover(self) -> None:
        """Scan plugin directories and register enabled plugins.

        Raises ``ValueError`` if an enabled plugin is not found on disk or
        fails to load.
        """
        if not self._enabled_plugins:
            return

        for dir_key, plugin_dir in self._plugin_dirs.items():
            ptype = _DIR_KEY_TO_TYPE.get(dir_key)
            if ptype is None:
                continue
            if not plugin_dir.is_dir():
                continue
            for child in sorted(plugin_dir.iterdir()):
                if not child.is_dir() or not (child / "__init__.py").exists():
                    continue
                if child.name not in self._enabled_plugins:
                    continue
                self._load_plugin(child.name, ptype, _TYPE_TO_DIR[ptype], child)

        # Check for enabled plugins that weren't found
        found = set(self._plugins.keys())
        missing = set(self._enabled_plugins) - found
        if missing:
            raise ValueError(
                f"Plugins listed in enabled_plugins but not found: {missing}"
            )

    def _load_plugin(
        self, name: str, ptype: PluginType, dirname: str, plugin_dir: Path
    ) -> None:
        module_path = f"phiacta.{dirname}.{name}"
        try:
            if self._use_file_loader:
                # Load from filesystem path (for testing with tmp_path)
                init_file = plugin_dir / "__init__.py"
                spec = importlib.util.spec_from_file_location(
                    module_path, init_file
                )
                if spec is None or spec.loader is None:
                    raise ImportError(f"Cannot load module from {init_file}")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_path] = module
                try:
                    spec.loader.exec_module(module)
                except Exception:
                    sys.modules.pop(module_path, None)
                    raise
            else:
                module = importlib.import_module(module_path)
        except Exception:
            logger.exception("Failed to import plugin %s", module_path)
            raise

        manifest = getattr(module, "manifest", None)
        if not isinstance(manifest, PluginManifest):
            raise ValueError(
                f"Plugin {module_path} does not expose a "
                f"PluginManifest as 'manifest'"
            )

        if manifest.name != name:
            raise ValueError(
                f"Plugin directory '{name}' does not match "
                f"manifest name '{manifest.name}'"
            )

        if manifest.type != ptype:
            raise ValueError(
                f"Plugin '{name}' is in directory '{dirname}' "
                f"(type={ptype.value}) but manifest declares "
                f"type={manifest.type.value}"
            )

        if manifest.name in self._plugins:
            raise ValueError(f"Duplicate plugin name: '{manifest.name}'")

        # Instantiate plugin-specific settings if defined
        settings = None
        if manifest.settings_class is not None:
            try:
                settings = manifest.settings_class()
            except Exception as exc:
                raise ValueError(
                    f"Plugin '{name}' settings failed to load. "
                    f"Check required env vars for "
                    f"{manifest.settings_class.__name__}: {exc}"
                ) from exc

        router = getattr(module, "router", None)
        edp = getattr(module, "entry_data_provider", None)
        on_ingest = getattr(module, "on_ingest", None)

        self._plugins[manifest.name] = PluginRegistration(
            manifest=manifest,
            router=router,
            settings=settings,
            entry_data_provider=edp,
            on_ingest=on_ingest,
        )

    def resolve_dependencies(self) -> list[str]:
        """Validate and topologically sort the dependency graph.

        Returns the plugin names in load order (dependencies first).
        Raises ``ValueError`` on missing dependencies or cycles.
        """
        # Check all depends_on reference registered plugins
        for name, reg in self._plugins.items():
            for dep in reg.manifest.depends_on:
                if dep not in self._plugins:
                    raise ValueError(
                        f"Plugin '{name}' depends on '{dep}', "
                        f"but '{dep}' is not enabled"
                    )

        # Kahn's algorithm for topological sort
        in_degree: dict[str, int] = {n: 0 for n in self._plugins}
        dependents: dict[str, list[str]] = {n: [] for n in self._plugins}

        for name, reg in self._plugins.items():
            for dep in reg.manifest.depends_on:
                in_degree[name] += 1
                dependents[dep].append(name)

        queue: deque[str] = deque(
            n for n, d in in_degree.items() if d == 0
        )
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for dependent in dependents[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self._plugins):
            remaining = [n for n, d in in_degree.items() if d > 0]
            raise ValueError(
                f"Circular dependency detected among plugins: "
                f"{', '.join(remaining)}"
            )

        return order

    def get_routers(self) -> list[tuple[str, APIRouter]]:
        """Return ``(prefix, router)`` tuples for all plugins with routers."""
        result: list[tuple[str, APIRouter]] = []
        for name, reg in self._plugins.items():
            if reg.router is not None:
                prefix = f"{_TYPE_TO_PREFIX[reg.manifest.type]}/{name}"
                result.append((prefix, reg.router))
        return result

    def get_manifests(self) -> list[PluginManifest]:
        """Return all registered plugin manifests."""
        return [reg.manifest for reg in self._plugins.values()]

    def get_entry_data_providers(self) -> list[EntryDataProvider]:
        """Return all registered entry data providers.

        Providers are returned in plugin registration order (which
        follows topological dependency order after resolve_dependencies).
        """
        from phiacta.core.compose import EntryDataProvider

        return [
            reg.entry_data_provider
            for reg in self._plugins.values()
            if reg.entry_data_provider is not None
        ]

    def get_on_ingest_hooks(self) -> list[OnIngestHook]:
        """Return all registered on_ingest hooks."""
        return [
            reg.on_ingest
            for reg in self._plugins.values()
            if reg.on_ingest is not None
        ]

    def get_settings(self, name: str) -> Any:
        """Get a plugin's settings instance.

        Returns ``None`` if the plugin has no settings_class.
        Raises ``KeyError`` if the plugin is not registered.
        """
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' is not registered")
        return self._plugins[name].settings
