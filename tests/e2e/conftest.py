# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E test fixtures.

Provides an httpx AsyncClient wired to the real FastAPI app with a test
database. Uses TEST_DATABASE_URL if set (real Postgres), otherwise falls
back to SQLite in-memory for environments without Docker.

The Forgejo-dependent tests are marked with ``@pytest.mark.forgejo`` and
require a running Forgejo instance (FORGEJO_URL env var).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from phiacta.api.rate_limit import limiter
from phiacta.db.session import get_db
from phiacta.main import app
from phiacta.models.base import Base


def _get_test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture
async def e2e_engine() -> AsyncIterator[AsyncEngine]:
    """Create an engine for the E2E test database."""
    url = _get_test_database_url()
    engine = create_async_engine(url, echo=False)

    # Enable FK enforcement for SQLite (off by default).
    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def e2e_session_factory(
    e2e_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        e2e_engine, class_=AsyncSession, expire_on_commit=False,
    )


@pytest.fixture
async def client(
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    """httpx AsyncClient wired to the FastAPI app with test DB."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with e2e_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # Disable rate limiting during tests.
    limiter.enabled = False

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    limiter.enabled = True
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def register_agent(
    client: httpx.AsyncClient,
    handle: str = "test-agent",
    email: str = "test@example.com",
    password: str = "TestPassword123!",
) -> dict:
    """Register an agent and return the full auth response."""
    resp = await client.post("/v1/auth/register", json={
        "handle": handle,
        "email": email,
        "password": password,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_header(token: str) -> dict[str, str]:
    """Return an Authorization header dict for the given token."""
    return {"Authorization": f"Bearer {token}"}
