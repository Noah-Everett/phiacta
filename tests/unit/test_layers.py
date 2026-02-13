# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from newpublishing.layers.base import Layer
from newpublishing.layers.confidence.layer import ConfidenceLayer
from newpublishing.layers.graph.layer import GraphLayer
from newpublishing.layers.registry import LayerRegistry

# -- Stub layer for testing --------------------------------------------------


class _StubLayer(Layer):
    @property
    def name(self) -> str:
        return "stub"

    @property
    def version(self) -> str:
        return "0.0.1"

    def router(self) -> APIRouter:
        r = APIRouter()

        @r.get("/ping")
        async def ping() -> dict[str, str]:
            return {"pong": "ok"}

        return r

    async def setup(self, engine: AsyncEngine) -> None:
        pass


# -- Layer ABC tests ----------------------------------------------------------


class TestLayerABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            Layer()  # type: ignore[abstract]

    def test_stub_layer_implements_abc(self) -> None:
        layer = _StubLayer()
        assert layer.name == "stub"
        assert layer.version == "0.0.1"
        assert layer.description == ""  # default
        assert isinstance(layer.router(), APIRouter)


# -- LayerRegistry tests ------------------------------------------------------


class TestLayerRegistry:
    def test_register_and_get(self) -> None:
        registry = LayerRegistry()
        layer = _StubLayer()
        registry.register(layer)
        assert registry.get("stub") is layer

    def test_get_missing_returns_none(self) -> None:
        registry = LayerRegistry()
        assert registry.get("nonexistent") is None

    def test_all_layers(self) -> None:
        registry = LayerRegistry()
        layer = _StubLayer()
        registry.register(layer)
        assert len(registry.all_layers()) == 1
        assert registry.all_layers()[0] is layer

    def test_duplicate_registration_raises(self) -> None:
        registry = LayerRegistry()
        registry.register(_StubLayer())
        with pytest.raises(ValueError, match="already registered"):
            registry.register(_StubLayer())

    def test_mount_all_adds_routes(self) -> None:
        registry = LayerRegistry()
        registry.register(_StubLayer())

        app = FastAPI()
        registry.mount_all(app)

        # Verify that routes were mounted under /layers/stub/
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/layers/stub/ping" in route_paths


# -- Built-in layer tests -----------------------------------------------------


class TestGraphLayer:
    def test_graph_layer_properties(self) -> None:
        layer = GraphLayer()
        assert layer.name == "graph"
        assert layer.version == "0.1.0"
        assert layer.description != ""

    def test_graph_layer_router_has_routes(self) -> None:
        layer = GraphLayer()
        router = layer.router()
        route_paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/edge-types" in route_paths
        assert "/claims/{claim_id}/neighbors" in route_paths
        assert "/traverse" in route_paths


class TestConfidenceLayer:
    def test_confidence_layer_properties(self) -> None:
        layer = ConfidenceLayer()
        assert layer.name == "confidence"
        assert layer.version == "0.1.0"
        assert layer.description != ""

    def test_confidence_layer_router_has_routes(self) -> None:
        layer = ConfidenceLayer()
        router = layer.router()
        route_paths = [r.path for r in router.routes if hasattr(r, "path")]
        assert "/claims/{claim_id}/status" in route_paths
        assert "/claims" in route_paths
