# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from phiacta.api.auth import limiter
from phiacta.api.router import v1_router
from phiacta.config import get_settings
from phiacta.db.session import get_engine
from phiacta.services.outbox_worker import start_outbox_worker
from phiacta.webhooks.forgejo import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown hooks."""
    from phiacta.layers.registry import LayerRegistry, discover_builtin_layers

    settings = get_settings()

    # Startup: auto-migrate in development mode
    if settings.environment == "development":
        import subprocess

        subprocess.run(["alembic", "upgrade", "head"], check=True)

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

    # Start outbox worker for Forgejo sync
    outbox_worker = await start_outbox_worker(engine)

    # Store on app state for access in endpoints
    app.state.layer_registry = registry
    app.state.engine = engine
    app.state.outbox_worker = outbox_worker

    yield

    # Shutdown: cleanup
    await outbox_worker.stop()
    await registry.teardown_all(engine)
    await engine.dispose()


app = FastAPI(
    title="Phiacta Knowledge Backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(v1_router, prefix="/v1")
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe. Returns 200 if the process is running."""
    return {"status": "healthy"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    """Readiness probe. Checks database connectivity."""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
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
