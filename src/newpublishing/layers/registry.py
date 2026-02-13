# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from newpublishing.layers.base import Layer


class LayerRegistry:
    """Manages discovery, lifecycle, and route mounting for layers."""

    def __init__(self) -> None:
        self._layers: dict[str, Layer] = {}

    def register(self, layer: Layer) -> None:
        """Add a layer. Raises ValueError if name already registered."""
        if layer.name in self._layers:
            msg = f"Layer '{layer.name}' is already registered"
            raise ValueError(msg)
        self._layers[layer.name] = layer

    def get(self, name: str) -> Layer | None:
        """Return a layer by name, or None."""
        return self._layers.get(name)

    def all_layers(self) -> list[Layer]:
        """Return all registered layers."""
        return list(self._layers.values())

    async def setup_all(self, engine: AsyncEngine) -> None:
        """Call setup() on each registered layer."""
        for layer in self._layers.values():
            await layer.setup(engine)

    def mount_all(self, app: FastAPI) -> None:
        """Mount each layer's router at /layers/{layer.name}/."""
        for layer in self._layers.values():
            app.include_router(
                layer.router(),
                prefix=f"/layers/{layer.name}",
                tags=[layer.name],
            )

    async def teardown_all(self, engine: AsyncEngine) -> None:
        """Call teardown() on each registered layer."""
        for layer in self._layers.values():
            await layer.teardown(engine)


def discover_builtin_layers() -> list[Layer]:
    """Import and instantiate built-in layers."""
    from newpublishing.layers.confidence.layer import ConfidenceLayer
    from newpublishing.layers.graph.layer import GraphLayer

    return [GraphLayer(), ConfidenceLayer()]
