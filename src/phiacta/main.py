# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from phiacta.core.middleware import ContentSizeLimitMiddleware
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from phiacta.config import get_settings
from phiacta.core.api.rate_limit import limiter
from phiacta.core.api.router import v1_router
from phiacta.core.db.session import get_engine
from phiacta.core.services.git_service_dep import close_git_service, get_git_service
from phiacta.core.services.outbox_worker import start_outbox_worker
from phiacta.core.webhooks.forgejo import router as webhook_router
from phiacta.plugin import PluginRegistry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown hooks."""
    settings = get_settings()

    # Plugin discovery and router mounting
    registry = PluginRegistry(enabled_plugins=settings.enabled_plugins)
    registry.discover()
    registry.resolve_dependencies()
    for prefix, router in registry.get_routers():
        app.include_router(router, prefix=prefix, tags=[prefix.rsplit("/", 1)[-1]])
    app.state.plugin_registry = registry

    # Startup: auto-migrate in development mode
    if settings.environment == "development":
        import subprocess

        subprocess.run(["alembic", "upgrade", "heads"], check=True)

    # Reuse the cached, properly-configured engine
    engine = get_engine()

    # Forgejo startup migrations — fix repo/user settings from older code.
    import logging
    _log = logging.getLogger(__name__)
    git_svc = get_git_service()
    try:
        counts = await git_svc.run_startup_migrations()
        if any(counts.values()):
            _log.info("Forgejo migrations: %s", counts)
    except Exception:
        _log.warning("Forgejo startup migrations failed", exc_info=True)

    # Start outbox worker for Forgejo sync (with view hooks)
    on_ingest_hooks = registry.get_on_ingest_hooks()
    outbox_worker = await start_outbox_worker(engine, on_ingest_hooks=on_ingest_hooks)

    # Store on app state for access in endpoints
    app.state.engine = engine
    app.state.outbox_worker = outbox_worker

    yield

    # Shutdown: cleanup
    await outbox_worker.stop()
    await close_git_service()
    await engine.dispose()


app = FastAPI(
    title="Phiacta Knowledge Backend",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
limiter.enabled = get_settings().rate_limit_enabled
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(ContentSizeLimitMiddleware, max_bytes=get_settings().max_json_body_bytes)

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
