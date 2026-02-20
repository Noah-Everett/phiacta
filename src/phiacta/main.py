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


@app.get("/debug/outbox")
async def debug_outbox(request: Request) -> dict[str, Any]:
    """Temporary debug endpoint: show outbox state."""
    engine = request.app.state.engine
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, operation, status, attempts, max_attempts, "
                "last_error, retry_after, created_at "
                "FROM outbox ORDER BY created_at"
            )
        )
        rows = result.mappings().all()
    return {
        "count": len(rows),
        "entries": [
            {
                "id": str(r["id"]),
                "operation": r["operation"],
                "status": r["status"],
                "attempts": r["attempts"],
                "max_attempts": r["max_attempts"],
                "last_error": r["last_error"],
                "retry_after": str(r["retry_after"]) if r["retry_after"] else None,
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ],
    }


@app.get("/debug/claims")
async def debug_claims(request: Request) -> dict[str, Any]:
    """Temporary debug endpoint: show claim repo statuses."""
    engine = request.app.state.engine
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, title, repo_status, forgejo_repo_id, "
                "current_head_sha, created_at "
                "FROM claims ORDER BY created_at"
            )
        )
        rows = result.mappings().all()
    return {
        "count": len(rows),
        "claims": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "repo_status": r["repo_status"],
                "forgejo_repo_id": r["forgejo_repo_id"],
                "current_head_sha": r["current_head_sha"],
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ],
    }


@app.delete("/debug/outbox")
async def debug_clear_outbox(request: Request) -> dict[str, Any]:
    """Temporary debug endpoint: delete all failed/stuck outbox entries
    and reset claims to 'error' so new ones can be created cleanly."""
    engine = request.app.state.engine
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM outbox WHERE status != 'completed' RETURNING id")
        )
        deleted = result.all()
        await conn.execute(
            text("UPDATE claims SET repo_status = 'error' WHERE repo_status = 'provisioning'")
        )
    return {"deleted_outbox_entries": len(deleted)}
