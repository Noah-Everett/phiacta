# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Plugin framework for Phiacta extensions, views, and tools.

Provides the manifest dataclass, plugin type enum, and the registry
that discovers, validates, and mounts plugins at startup.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import APIRouter
    from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class PluginType(Enum):
    """Type of plugin: extension, view, or tool."""

    EXTENSION = "extension"
    VIEW = "view"
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
    settings: Any = None


# Maps PluginType to the directory name under src/phiacta/
_TYPE_TO_DIR: dict[PluginType, str] = {
    PluginType.EXTENSION: "extensions",
    PluginType.VIEW: "views",
    PluginType.TOOL: "tools",
}

# Maps PluginType to the URL prefix for router mounting
_TYPE_TO_PREFIX: dict[PluginType, str] = {
    PluginType.EXTENSION: "/v1/extensions",
    PluginType.VIEW: "/v1/views",
    PluginType.TOOL: "/v1/tools",
}

# Maps plugin_dirs key to PluginType
_DIR_KEY_TO_TYPE: dict[str, PluginType] = {
    "extension": PluginType.EXTENSION,
    "view": PluginType.VIEW,
    "tool": PluginType.TOOL,
}


class PluginRegistry:
    """Discovers, validates, and registers plugins at startup.

    Parameters
    ----------
    plugin_dirs
        Mapping of plugin type key ("extension", "view", "tool") to the
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

        self._custom_dirs = plugin_dirs is not None
        if plugin_dirs is not None:
            self._plugin_dirs = plugin_dirs
        else:
            package_root = Path(__file__).parent
            self._plugin_dirs = {
                "extension": package_root / "extensions",
                "view": package_root / "views",
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
            if self._custom_dirs:
                # Load from filesystem path (for testing with tmp_path)
                init_file = plugin_dir / "__init__.py"
                spec = importlib.util.spec_from_file_location(
                    module_path, init_file
                )
                if spec is None or spec.loader is None:
                    raise ImportError(f"Cannot load module from {init_file}")
                module = importlib.util.module_from_spec(spec)
                import sys

                sys.modules[module_path] = module
                spec.loader.exec_module(module)
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

        self._plugins[manifest.name] = PluginRegistration(
            manifest=manifest,
            router=router,
            settings=settings,
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
        # adjacency: dep -> list of dependents
        dependents: dict[str, list[str]] = {n: [] for n in self._plugins}

        for name, reg in self._plugins.items():
            for dep in reg.manifest.depends_on:
                in_degree[name] += 1
                dependents[dep].append(name)

        queue = [n for n, d in in_degree.items() if d == 0]
        order: list[str] = []

        while queue:
            node = queue.pop(0)
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

    def get_routers(self) -> list[tuple[str, Any]]:
        """Return ``(prefix, router)`` tuples for all plugins with routers."""
        result: list[tuple[str, Any]] = []
        for name, reg in self._plugins.items():
            if reg.router is not None:
                prefix = f"{_TYPE_TO_PREFIX[reg.manifest.type]}/{name}"
                result.append((prefix, reg.router))
        return result

    def get_settings(self, name: str) -> Any:
        """Get a plugin's settings instance.

        Returns ``None`` if the plugin has no settings_class.
        Raises ``KeyError`` if the plugin is not registered.
        """
        if name not in self._plugins:
            raise KeyError(f"Plugin '{name}' is not registered")
        return self._plugins[name].settings
