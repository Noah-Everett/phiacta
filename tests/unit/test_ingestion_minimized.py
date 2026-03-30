# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for ingestion after entry minimization."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.core.models.entry import Entry
from phiacta.core.services.ingestion import ingest_entry
from tests.conftest import make_user, make_entry
from tests.e2e.conftest import FakeGitService


def _make_yaml(entry_id: UUID, author_id: UUID | None = None) -> bytes:
    return yaml.dump({"entry_id": f"ent_{entry_id}", "schema_version": 1, "author": {"id": f"usr_{author_id or uuid4()}", "name": "test"}, "created_at": "2026-01-01T00:00:00"}, sort_keys=False).encode()


async def _create(db: AsyncSession, visibility="public"):
    user = User(**make_user())
    db.add(user)
    await db.flush()
    entry = Entry(**make_entry(created_by=user.id, visibility=visibility))
    db.add(entry)
    await db.flush()
    return entry, user


class TestIngestContent:
    async def test_reads_content_md(self, db_session: AsyncSession) -> None:
        entry, user = await _create(db_session)
        fake = FakeGitService()
        fake.files[(entry.id, ".phiacta/entry.yaml")] = _make_yaml(entry.id, user.id)
        fake.files[(entry.id, ".phiacta/content.md")] = b"# Quantum\n\nPhysics."
        await ingest_entry(entry, "a" * 40, db_session, fake)
        assert not hasattr(entry, "content_cache")

    async def test_handles_no_content_file(self, db_session: AsyncSession) -> None:
        entry, user = await _create(db_session)
        fake = FakeGitService()
        fake.files[(entry.id, ".phiacta/entry.yaml")] = _make_yaml(entry.id, user.id)
        await ingest_entry(entry, "a" * 40, db_session, fake)


class TestIngestIdentity:
    async def test_does_not_write_title(self, db_session: AsyncSession) -> None:
        entry, user = await _create(db_session)
        fake = FakeGitService()
        fake.files[(entry.id, ".phiacta/entry.yaml")] = _make_yaml(entry.id, user.id)
        await ingest_entry(entry, "a" * 40, db_session, fake)
        assert not hasattr(entry, "title")


class TestIngestNoRefs:
    async def test_refs_yaml_ignored(self, db_session: AsyncSession) -> None:
        entry, user = await _create(db_session)
        fake = FakeGitService()
        fake.files[(entry.id, ".phiacta/entry.yaml")] = _make_yaml(entry.id, user.id)
        fake.files[(entry.id, ".phiacta/refs.yaml")] = yaml.dump({"refs": [{"rel": "evidence", "target": {"entry_id": f"ent_{uuid4()}"}}]}).encode()
        await ingest_entry(entry, "a" * 40, db_session, fake)


class TestIngestWithoutEntryYaml:
    """entry.yaml is no longer read during ingestion."""

    async def test_succeeds_without_entry_yaml(self, db_session: AsyncSession) -> None:
        """Ingestion works even when no entry.yaml exists in the repo."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        fake.files[(entry.id, ".phiacta/content.md")] = b"# Content"
        await ingest_entry(entry, "a" * 40, db_session, fake)

    async def test_ignores_malformed_entry_yaml(self, db_session: AsyncSession) -> None:
        """Malformed entry.yaml is silently ignored (no longer parsed)."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        fake.files[(entry.id, ".phiacta/entry.yaml")] = b": invalid: {{"
        fake.files[(entry.id, ".phiacta/content.md")] = b"# Content"
        await ingest_entry(entry, "a" * 40, db_session, fake)
