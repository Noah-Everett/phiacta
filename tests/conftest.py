# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from newpublishing.config import get_settings


@pytest.fixture
async def async_engine():  # type: ignore[no-untyped-def]
    """Create an async engine for the test database."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(  # type: ignore[no-untyped-def]
    async_engine,  # type: ignore[no-untyped-def]
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
