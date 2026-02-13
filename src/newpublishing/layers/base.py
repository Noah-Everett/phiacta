# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from abc import ABC, abstractmethod

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncEngine


class Layer(ABC):
    """Base class for interpretability layers.

    A layer reads core data (claims, relations, reviews, etc.) and provides
    its own tables, views, and API endpoints for interpreted queries.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this layer (e.g. 'graph', 'confidence')."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Semantic version string (e.g. '0.1.0')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what this layer does."""
        return ""

    @abstractmethod
    def router(self) -> APIRouter:
        """Return a FastAPI router. Mounted at /layers/{name}/."""
        ...

    @abstractmethod
    async def setup(self, engine: AsyncEngine) -> None:
        """Create any tables/views this layer needs.

        Called once on startup. Use CREATE TABLE IF NOT EXISTS /
        CREATE OR REPLACE VIEW for idempotency.
        """
        ...

    async def teardown(self, engine: AsyncEngine) -> None:  # noqa: B027
        """Optional cleanup on shutdown. Default is no-op."""
