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
from phiacta.plugin import IngestContext, IngestTrigger
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


class TestTriggerFiltering:
    """Verify that ingest_entry skips/runs hooks based on IngestContext."""

    @staticmethod
    def _make_hook(name: str, triggers: set[IngestTrigger] | None = None):
        """Create a mock on_ingest hook that records calls."""
        calls: list[UUID] = []

        async def hook(entity_id, content, metadata, db):
            calls.append(entity_id)

        hook.__name__ = name  # type: ignore[attr-defined]
        hook.calls = calls  # type: ignore[attr-defined]
        if triggers is not None:
            hook.triggers = triggers  # type: ignore[attr-defined]
        return hook

    async def test_hook_with_matching_trigger_runs(self, db_session: AsyncSession) -> None:
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", {IngestTrigger.CONTENT_CHANGED})
        ctx = IngestContext(trigger=IngestTrigger.CONTENT_CHANGED)

        await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=ctx)
        assert len(hook.calls) == 1

    async def test_hook_with_non_matching_trigger_skipped(self, db_session: AsyncSession) -> None:
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", {IngestTrigger.CONTENT_CHANGED})
        ctx = IngestContext(trigger=IngestTrigger.INITIAL_PROVISION)

        await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=ctx)
        assert len(hook.calls) == 0

    async def test_hook_without_triggers_always_runs(self, db_session: AsyncSession) -> None:
        """Hooks without a triggers attribute run on every context (backward compat)."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", triggers=None)

        for trigger in IngestTrigger:
            ctx = IngestContext(trigger=trigger)
            await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=ctx)
        assert len(hook.calls) == len(IngestTrigger)

    async def test_no_context_runs_all_hooks(self, db_session: AsyncSession) -> None:
        """When context is None, all hooks run (backward compat)."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", {IngestTrigger.CONTENT_CHANGED})

        await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=None)
        assert len(hook.calls) == 1

    async def test_mixed_hooks_filtered_correctly(self, db_session: AsyncSession) -> None:
        """With multiple hooks, only matching ones run."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        content_hook = self._make_hook("content", {IngestTrigger.CONTENT_CHANGED})
        always_hook = self._make_hook("always", triggers=None)
        recon_hook = self._make_hook("recon", {IngestTrigger.RECONCILIATION})
        ctx = IngestContext(trigger=IngestTrigger.CONTENT_CHANGED)

        await ingest_entry(
            entry, "a" * 40, db_session, fake,
            on_ingest_hooks=[content_hook, always_hook, recon_hook],
            context=ctx,
        )
        assert len(content_hook.calls) == 1
        assert len(always_hook.calls) == 1
        assert len(recon_hook.calls) == 0


class TestPathFiltering:
    """Verify that ingest_entry skips/runs hooks based on path_patterns."""

    @staticmethod
    def _make_hook(
        name: str,
        path_patterns: tuple[str, ...] | None = None,
    ):
        calls: list[UUID] = []

        async def hook(entity_id, content, metadata, db):
            calls.append(entity_id)

        hook.__name__ = name  # type: ignore[attr-defined]
        hook.calls = calls  # type: ignore[attr-defined]
        if path_patterns is not None:
            hook.path_patterns = path_patterns  # type: ignore[attr-defined]
        return hook

    async def test_matching_pattern_runs(self, db_session: AsyncSession) -> None:
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", (".phiacta/content.*",))
        ctx = IngestContext(
            trigger=IngestTrigger.CONTENT_CHANGED,
            changed_paths=frozenset({".phiacta/content.md"}),
        )
        await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=ctx)
        assert len(hook.calls) == 1

    async def test_non_matching_pattern_skipped(self, db_session: AsyncSession) -> None:
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", (".phiacta/content.*",))
        ctx = IngestContext(
            trigger=IngestTrigger.CONTENT_CHANGED,
            changed_paths=frozenset({"figures/diagram.png"}),
        )
        await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=ctx)
        assert len(hook.calls) == 0

    async def test_no_path_patterns_always_runs(self, db_session: AsyncSession) -> None:
        """Hooks without path_patterns run on any file change (backward compat)."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", path_patterns=None)
        ctx = IngestContext(
            trigger=IngestTrigger.CONTENT_CHANGED,
            changed_paths=frozenset({"figures/diagram.png"}),
        )
        await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=ctx)
        assert len(hook.calls) == 1

    async def test_empty_changed_paths_skips_filtering(self, db_session: AsyncSession) -> None:
        """When changed_paths is empty (reconciliation/outbox), path filtering is skipped."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", (".phiacta/content.*",))
        ctx = IngestContext(trigger=IngestTrigger.RECONCILIATION, changed_paths=frozenset())
        await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=ctx)
        assert len(hook.calls) == 1

    async def test_no_context_runs_all_hooks(self, db_session: AsyncSession) -> None:
        """When context is None, path filtering is skipped (backward compat)."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        hook = self._make_hook("test", (".phiacta/content.*",))
        await ingest_entry(entry, "a" * 40, db_session, fake, on_ingest_hooks=[hook], context=None)
        assert len(hook.calls) == 1

    async def test_mixed_hooks_path_filtered(self, db_session: AsyncSession) -> None:
        """Narrow-pattern hook skipped, no-pattern hook runs (figure-only push)."""
        entry, _ = await _create(db_session)
        fake = FakeGitService()
        search_hook = self._make_hook("search", (".phiacta/content.*", ".phiacta/content/*"))
        compile_hook = self._make_hook("compile", path_patterns=None)
        ctx = IngestContext(
            trigger=IngestTrigger.CONTENT_CHANGED,
            changed_paths=frozenset({"figures/diagram.png"}),
        )
        await ingest_entry(
            entry, "a" * 40, db_session, fake,
            on_ingest_hooks=[search_hook, compile_hook],
            context=ctx,
        )
        assert len(search_hook.calls) == 0
        assert len(compile_hook.calls) == 1


class TestAnyHookMatches:
    """Verify _any_hook_matches (the webhook outer gate)."""

    @staticmethod
    def _make_hook(name: str, path_patterns: tuple[str, ...] | None = None):
        async def hook(entity_id, content, metadata, db):
            pass
        hook.__name__ = name  # type: ignore[attr-defined]
        if path_patterns is not None:
            hook.path_patterns = path_patterns  # type: ignore[attr-defined]
        return hook

    @staticmethod
    def _commits(paths: list[str]) -> list[dict]:
        return [{"added": paths, "modified": [], "removed": []}]

    def test_hook_without_patterns_always_matches(self) -> None:
        from phiacta.core.webhooks.forgejo import _any_hook_matches
        hook = self._make_hook("all")
        assert _any_hook_matches(self._commits(["anything.txt"]), [hook]) is True

    def test_matching_glob_pattern(self) -> None:
        from phiacta.core.webhooks.forgejo import _any_hook_matches
        hook = self._make_hook("search", (".phiacta/content.*",))
        assert _any_hook_matches(self._commits([".phiacta/content.md"]), [hook]) is True

    def test_non_matching_pattern(self) -> None:
        from phiacta.core.webhooks.forgejo import _any_hook_matches
        hook = self._make_hook("search", (".phiacta/content.*",))
        assert _any_hook_matches(self._commits(["figures/diagram.png"]), [hook]) is False

    def test_empty_commits_returns_true(self) -> None:
        from phiacta.core.webhooks.forgejo import _any_hook_matches
        hook = self._make_hook("search", (".phiacta/content.*",))
        assert _any_hook_matches([], [hook]) is True

    def test_multiple_hooks_one_matches(self) -> None:
        from phiacta.core.webhooks.forgejo import _any_hook_matches
        narrow = self._make_hook("narrow", (".phiacta/content.*",))
        broad = self._make_hook("broad", ("*.bib",))
        assert _any_hook_matches(self._commits(["refs.bib"]), [narrow, broad]) is True

    def test_wildcard_pattern(self) -> None:
        from phiacta.core.webhooks.forgejo import _any_hook_matches
        hook = self._make_hook("bib", ("*.bib",))
        assert _any_hook_matches(self._commits(["refs.bib"]), [hook]) is True
        assert _any_hook_matches(self._commits(["refs.txt"]), [hook]) is False
