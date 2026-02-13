# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

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

from newpublishing.models.base import Base


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
    name: str = "Test Agent",
    external_id: str | None = None,
    trust_score: float = 1.0,
) -> dict[str, object]:
    """Return kwargs suitable for constructing an Agent model instance."""
    return {
        "id": uuid4(),
        "agent_type": agent_type,
        "name": name,
        "external_id": external_id,
        "trust_score": trust_score,
        "attrs": {},
    }


def make_namespace(
    *,
    name: str = "test-namespace",
    description: str | None = "A test namespace",
) -> dict[str, object]:
    """Return kwargs suitable for constructing a Namespace model instance."""
    return {
        "id": uuid4(),
        "name": name,
        "description": description,
        "attrs": {},
    }


def make_claim(
    *,
    namespace_id: object,
    created_by: object,
    content: str = "Test claim content",
    claim_type: str = "assertion",
    version: int = 1,
    lineage_id: object | None = None,
    status: str = "active",
) -> dict[str, object]:
    """Return kwargs suitable for constructing a Claim model instance."""
    return {
        "id": uuid4(),
        "lineage_id": lineage_id or uuid4(),
        "version": version,
        "content": content,
        "claim_type": claim_type,
        "namespace_id": namespace_id,
        "created_by": created_by,
        "status": status,
        "attrs": {},
    }


def make_source(
    *,
    submitted_by: object,
    source_type: str = "manual_entry",
    title: str | None = "Test Source",
    external_ref: str | None = None,
    content_hash: str | None = None,
) -> dict[str, object]:
    """Return kwargs suitable for constructing a Source model instance."""
    return {
        "id": uuid4(),
        "source_type": source_type,
        "title": title,
        "submitted_by": submitted_by,
        "external_ref": external_ref,
        "content_hash": content_hash,
        "attrs": {},
    }


def make_relation(
    *,
    source_id: object,
    target_id: object,
    created_by: object,
    relation_type: str = "supports",
    strength: float | None = None,
) -> dict[str, object]:
    """Return kwargs suitable for constructing a Relation model instance."""
    return {
        "id": uuid4(),
        "source_id": source_id,
        "target_id": target_id,
        "relation_type": relation_type,
        "created_by": created_by,
        "strength": strength,
        "attrs": {},
    }


def make_bundle(
    *,
    submitted_by: object,
    idempotency_key: str | None = None,
    extension_id: str = "test-extension",
    status: str = "accepted",
) -> dict[str, object]:
    """Return kwargs suitable for constructing a Bundle model instance."""
    return {
        "id": uuid4(),
        "idempotency_key": idempotency_key or str(uuid4()),
        "submitted_by": submitted_by,
        "extension_id": extension_id,
        "status": status,
        "attrs": {},
    }
