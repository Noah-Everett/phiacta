# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from phiacta.core.models.base import Base


def _get_test_database_url() -> str:
    """Return the test database URL from env, falling back to SQLite for unit tests."""
    return os.environ.get(
        "TEST_DATABASE_URL",
        "sqlite+aiosqlite:///:memory:",
    )


@pytest.fixture
async def async_engine() -> AsyncIterator[AsyncEngine]:
    """Create an async engine for the test database."""
    url = _get_test_database_url()
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(
    async_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """Provide a transactional database session that rolls back after each test."""
    session_factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Factory helpers for creating model instances in tests
# ---------------------------------------------------------------------------


def make_agent(
    *,
    agent_type: str = "human",
    handle: str = "test-agent",
    email: str = "test@example.com",
    password_hash: str = "$2b$12$fakehash",
) -> dict[str, object]:
    """Return kwargs suitable for constructing an Agent model instance."""
    return {
        "id": uuid4(),
        "agent_type": agent_type,
        "handle": handle,
        "email": email,
        "password_hash": password_hash,
    }


def make_entry(
    *,
    created_by: object,
    title: str = "Test Entry",
    content_format: str = "markdown",
    repo_name: str | None = None,
    layout_hint: str | None = None,
    tags: list[str] | None = None,
    summary: str | None = None,
    license_: str | None = None,
    status: str = "active",
) -> dict[str, object]:
    """Return kwargs suitable for constructing an Entry model instance."""
    entry_id = uuid4()
    return {
        "id": entry_id,
        "title": title,
        "content_format": content_format,
        "repo_name": repo_name or str(entry_id),
        "created_by": created_by,
        "layout_hint": layout_hint,
        "tags": tags or [],
        "summary": summary,
        "license": license_,
        "status": status,
    }


def make_entry_ref(
    *,
    from_entry_id: object,
    to_entry_id: object,
    rel: str = "evidence",
    version_sha: str | None = None,
    note: str | None = None,
) -> dict[str, object]:
    """Return kwargs suitable for constructing an EntryRef model instance."""
    return {
        "id": uuid4(),
        "from_entry_id": from_entry_id,
        "to_entry_id": to_entry_id,
        "rel": rel,
        "version_sha": version_sha,
        "note": note,
    }
