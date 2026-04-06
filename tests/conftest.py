# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine,
)

from phiacta.core.models.base import Base


def _get_test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture
async def async_engine() -> AsyncIterator[AsyncEngine]:
    url = _get_test_database_url()
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


def make_user(*, username: str = "test-user", password_hash: str = "$2b$12$fakehash") -> dict[str, object]:
    return {"id": uuid4(), "username": username, "password_hash": password_hash}


def make_entry(*, created_by: object, repo_name: str | None = None, visibility: str = "public") -> dict[str, object]:
    entry_id = uuid4()
    return {"id": entry_id, "repo_name": repo_name or str(entry_id), "created_by": created_by, "visibility": visibility}
