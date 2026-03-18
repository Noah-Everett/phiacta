# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for the extracted ingestion function (NEV-164).

Tests services/ingestion.py::ingest_entry() in isolation. Uses a real
in-memory SQLite database (via the conftest fixtures) with a FakeGitService.

The ingest_entry function:
1. Fetches .phiacta/entry.yaml from git and parses it
2. Updates entry metadata fields (title, tags, summary, etc.)
3. Fetches README{ext} and updates content_cache
4. Fetches .phiacta/refs.yaml and syncs entry_refs
5. Does NOT update current_head_sha (caller responsibility)
"""

from __future__ import annotations

from uuid import UUID, uuid4

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.entry import Entry
from phiacta.models.entry_ref import EntryRef
from phiacta.services.ingestion import ingest_entry
from tests.conftest import make_agent, make_entry
from tests.e2e.conftest import FakeGitService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry_yaml_bytes(
    entry_id: UUID,
    *,
    title: str = "Test Entry",
    content_format: str = "markdown",
    author_id: UUID | None = None,
    author_handle: str = "test-author",
    tags: list[str] | None = None,
    summary: str | None = None,
    license_: str | None = None,
    layout_hint: str | None = None,
) -> bytes:
    """Build valid entry.yaml bytes."""
    data: dict = {
        "entry_id": f"ent_{entry_id}",
        "schema_version": 1,
        "title": title,
        "author": {
            "id": f"usr_{author_id or uuid4()}",
            "name": author_handle,
        },
        "created_at": "2026-01-01T00:00:00",
        "content_format": content_format,
    }
    if tags:
        data["tags"] = tags
    if summary:
        data["summary"] = summary
    if license_:
        data["license"] = license_
    if layout_hint:
        data["layout_hint"] = layout_hint
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False).encode()


def _make_refs_yaml_bytes(refs: list[dict]) -> bytes:
    """Build valid refs.yaml bytes."""
    return yaml.dump(
        {"refs": refs},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).encode()


async def _create_test_entry(
    db_session: AsyncSession,
    *,
    title: str = "Test Entry",
    status: str = "active",
    content_format: str = "markdown",
    tags: list[str] | None = None,
) -> tuple[Entry, Agent]:
    """Create an agent and entry in the test DB, return (entry, agent)."""
    agent = Agent(**make_agent())
    db_session.add(agent)
    await db_session.flush()

    entry_kwargs = make_entry(
        created_by=agent.id,
        title=title,
        status=status,
        content_format=content_format,
        tags=tags,
    )
    entry = Entry(**entry_kwargs)
    db_session.add(entry)
    await db_session.flush()
    return entry, agent


# ---------------------------------------------------------------------------
# Tests: Metadata ingestion
# ---------------------------------------------------------------------------


class TestIngestEntryMetadata:
    """ingest_entry() should update entry metadata from entry.yaml."""

    async def test_updates_title_from_yaml(self, db_session: AsyncSession) -> None:
        entry, agent = await _create_test_entry(db_session, title="Old Title")
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id, title="New Title From Git", author_id=agent.id
        )

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.title == "New Title From Git"

    async def test_updates_tags_from_yaml(self, db_session: AsyncSession) -> None:
        entry, agent = await _create_test_entry(db_session, title="Tags Entry")
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id,
            title="Tags Entry",
            author_id=agent.id,
            tags=["physics", "quantum"],
        )

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.tags == ["physics", "quantum"]

    async def test_updates_summary_from_yaml(self, db_session: AsyncSession) -> None:
        entry, agent = await _create_test_entry(db_session)
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id,
            title="Summary Entry",
            author_id=agent.id,
            summary="A deep investigation into quantum entanglement",
        )

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.summary == "A deep investigation into quantum entanglement"

    async def test_updates_content_format_from_yaml(self, db_session: AsyncSession) -> None:
        entry, agent = await _create_test_entry(db_session)
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id,
            title="LaTeX Entry",
            author_id=agent.id,
            content_format="latex",
        )

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.content_format == "latex"

    async def test_updates_license_from_yaml(self, db_session: AsyncSession) -> None:
        entry, agent = await _create_test_entry(db_session)
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id,
            title="Licensed",
            author_id=agent.id,
            license_="MIT",
        )

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.license == "MIT"

    async def test_updates_layout_hint_from_yaml(self, db_session: AsyncSession) -> None:
        entry, agent = await _create_test_entry(db_session)
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id,
            title="Theorem",
            author_id=agent.id,
            layout_hint="theorem",
        )

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.layout_hint == "theorem"

    async def test_does_not_update_current_head_sha(self, db_session: AsyncSession) -> None:
        """ingest_entry MUST NOT update current_head_sha. That is the caller's
        responsibility after successful ingestion."""
        entry, agent = await _create_test_entry(db_session)
        old_sha = "z" * 40
        entry.current_head_sha = old_sha
        await db_session.flush()

        fake_git = FakeGitService()
        new_sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id, title="Updated", author_id=agent.id
        )

        await ingest_entry(entry, new_sha, db_session, fake_git)

        # current_head_sha should remain at old value
        assert entry.current_head_sha == old_sha


# ---------------------------------------------------------------------------
# Tests: Content cache ingestion
# ---------------------------------------------------------------------------


class TestIngestEntryContentCache:
    """ingest_entry() should update content_cache from README."""

    async def test_updates_content_cache_from_readme_md(
        self, db_session: AsyncSession
    ) -> None:
        entry, agent = await _create_test_entry(db_session)
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id, title="Content Entry", author_id=agent.id
        )
        fake_git.files[(entry.id, "README.md")] = b"# Hello World\n\nSome content."

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.content_cache == "# Hello World\n\nSome content."

    async def test_uses_correct_extension_for_latex(
        self, db_session: AsyncSession
    ) -> None:
        """LaTeX entries should look for README.tex, not README.md."""
        entry, agent = await _create_test_entry(db_session, content_format="latex")
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id, title="LaTeX", author_id=agent.id, content_format="latex"
        )
        fake_git.files[(entry.id, "README.tex")] = b"\\section{Introduction}"

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.content_cache == "\\section{Introduction}"

    async def test_missing_readme_sets_content_cache_to_none(
        self, db_session: AsyncSession
    ) -> None:
        """If README does not exist, content_cache should be set to None."""
        entry, agent = await _create_test_entry(db_session)
        entry.content_cache = "Old cached content"
        await db_session.flush()

        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry.id, title="No README", author_id=agent.id
        )
        # No README.md file in fake_git

        await ingest_entry(entry, sha, db_session, fake_git)

        assert entry.content_cache is None


# ---------------------------------------------------------------------------
# Tests: Refs ingestion
# ---------------------------------------------------------------------------


class TestIngestEntryRefs:
    """ingest_entry() should sync entry_refs from refs.yaml."""

    async def test_creates_refs_from_refs_yaml(self, db_session: AsyncSession) -> None:
        """Valid refs.yaml creates entry_ref rows."""
        entry_a, agent = await _create_test_entry(db_session, title="Source")
        entry_b_kwargs = make_entry(created_by=agent.id, title="Target")
        entry_b = Entry(**entry_b_kwargs)
        db_session.add(entry_b)
        await db_session.flush()

        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry_a.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry_a.id, title="Source", author_id=agent.id
        )
        fake_git.files[(entry_a.id, ".phiacta/refs.yaml")] = _make_refs_yaml_bytes([
            {
                "rel": "evidence",
                "target": {"entry_id": f"ent_{entry_b.id}"},
                "note": "Supports the claim",
            }
        ])

        await ingest_entry(entry_a, sha, db_session, fake_git)
        await db_session.flush()

        # Verify ref was created
        result = await db_session.execute(
            select(EntryRef).where(EntryRef.from_entry_id == entry_a.id)
        )
        refs = list(result.scalars().all())
        assert len(refs) == 1
        assert refs[0].to_entry_id == entry_b.id
        assert refs[0].rel == "evidence"
        assert refs[0].note == "Supports the claim"

    async def test_missing_refs_yaml_deletes_existing_refs(
        self, db_session: AsyncSession
    ) -> None:
        """If refs.yaml is missing, all outgoing refs should be deleted."""
        entry_a, agent = await _create_test_entry(db_session, title="Source")
        entry_b_kwargs = make_entry(created_by=agent.id, title="Target")
        entry_b = Entry(**entry_b_kwargs)
        db_session.add(entry_b)
        await db_session.flush()

        # Pre-create a ref
        ref = EntryRef(
            from_entry_id=entry_a.id,
            to_entry_id=entry_b.id,
            rel="evidence",
        )
        db_session.add(ref)
        await db_session.flush()

        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry_a.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry_a.id, title="Source", author_id=agent.id
        )
        # No refs.yaml file

        await ingest_entry(entry_a, sha, db_session, fake_git)
        await db_session.flush()

        result = await db_session.execute(
            select(EntryRef).where(EntryRef.from_entry_id == entry_a.id)
        )
        refs = list(result.scalars().all())
        assert len(refs) == 0


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------


class TestIngestEntryErrors:
    """ingest_entry() should raise on malformed data."""

    async def test_raises_on_malformed_entry_yaml(
        self, db_session: AsyncSession
    ) -> None:
        """Malformed entry.yaml should cause ingest_entry to raise."""
        import pytest

        entry, _ = await _create_test_entry(db_session)
        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = b": invalid: yaml: {{"

        with pytest.raises(ValueError, match="Invalid YAML"):
            await ingest_entry(entry, sha, db_session, fake_git)

    async def test_raises_on_missing_entry_yaml(
        self, db_session: AsyncSession
    ) -> None:
        """Missing entry.yaml should cause ingest_entry to raise."""
        import pytest

        from phiacta.services.git_service import RepoNotFoundError

        entry, _ = await _create_test_entry(db_session)
        fake_git = FakeGitService()
        sha = "a" * 40

        # No entry.yaml in fake_git

        with pytest.raises(RepoNotFoundError):
            await ingest_entry(entry, sha, db_session, fake_git)

    async def test_raises_on_entry_id_mismatch(
        self, db_session: AsyncSession
    ) -> None:
        """entry.yaml with wrong entry_id should cause ingest_entry to raise."""
        import pytest

        entry, agent = await _create_test_entry(db_session, title="Original")
        fake_git = FakeGitService()
        sha = "a" * 40

        wrong_id = uuid4()
        fake_git.files[(entry.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            wrong_id,  # wrong entry_id
            title="Should Not Apply",
            author_id=agent.id,
        )

        with pytest.raises(ValueError, match="entry_id mismatch"):
            await ingest_entry(entry, sha, db_session, fake_git)

    async def test_malformed_refs_yaml_leaves_existing_refs_unchanged(
        self, db_session: AsyncSession
    ) -> None:
        """Malformed refs.yaml should not delete or modify existing refs."""
        entry_a, agent = await _create_test_entry(db_session, title="Source")
        entry_b_kwargs = make_entry(created_by=agent.id, title="Target")
        entry_b = Entry(**entry_b_kwargs)
        db_session.add(entry_b)
        await db_session.flush()

        # Pre-create a ref
        ref = EntryRef(
            from_entry_id=entry_a.id,
            to_entry_id=entry_b.id,
            rel="evidence",
        )
        db_session.add(ref)
        await db_session.flush()

        fake_git = FakeGitService()
        sha = "a" * 40

        fake_git.files[(entry_a.id, ".phiacta/entry.yaml")] = _make_entry_yaml_bytes(
            entry_a.id, title="Source", author_id=agent.id
        )
        fake_git.files[(entry_a.id, ".phiacta/refs.yaml")] = b"invalid: {{"

        await ingest_entry(entry_a, sha, db_session, fake_git)
        await db_session.flush()

        # Refs should be unchanged
        result = await db_session.execute(
            select(EntryRef).where(EntryRef.from_entry_id == entry_a.id)
        )
        refs = list(result.scalars().all())
        assert len(refs) == 1
        assert refs[0].rel == "evidence"
