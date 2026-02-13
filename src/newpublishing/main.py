# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import create_async_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown hooks."""
    from newpublishing.config import get_settings
    from newpublishing.layers.registry import LayerRegistry, discover_builtin_layers

    settings = get_settings()

    # Startup: auto-migrate in development mode
    if settings.environment == "development":
        from alembic import command
        from alembic.config import Config

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")

    # Create async engine for layer setup
    engine = create_async_engine(settings.database_url)

    # Discover and register layers
    registry = LayerRegistry()
    if settings.auto_install_layers:
        for layer in discover_builtin_layers():
            registry.register(layer)

    # Setup layers (create their tables/views)
    await registry.setup_all(engine)

    # Mount layer routes
    registry.mount_all(app)

    # Store on app state for access in endpoints
    app.state.layer_registry = registry
    app.state.engine = engine

    yield

    # Shutdown: cleanup
    await registry.teardown_all(engine)
    await engine.dispose()


app = FastAPI(
    title="NewPublishing Knowledge Backend",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Returns 200 if the process is running."""
    return {"status": "healthy"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    """Readiness probe. Checks database connectivity."""
    # TODO: Check database connectivity
    return {"status": "ready"}


@app.get("/layers")
async def list_layers(request: Request) -> list[dict[str, Any]]:
    """List all installed interpretability layers."""
    registry = request.app.state.layer_registry
    return [
        {
            "name": layer.name,
            "version": layer.version,
            "description": layer.description,
        }
        for layer in registry.all_layers()
    ]
