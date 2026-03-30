# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests for the outbox worker.

These tests exercise the OutboxWorker methods against a real async database
(SQLite in-memory) with a mocked ForgejoGitService.  Each test creates
outbox entries directly in the DB and calls worker methods, verifying
side-effects on both the outbox table and the entries table.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from phiacta.core.models.entry import Entry
from phiacta.core.models.outbox import Outbox
from phiacta.core.models.user import User
from phiacta.core.services.git_service import (
    ForgejoError,
    ForgejoUnavailableError,
    RepoNotFoundError,
)
from phiacta.core.services.outbox_worker import OutboxWorker, _MAX_ATTEMPTS

# Import extension models so Base.metadata.create_all includes their tables.
import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401
import phiacta.extensions.search_tsv.models  # noqa: F401

from tests.conftest import make_user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def session_factory(
    async_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False,
    )


@pytest.fixture
async def worker(async_engine: AsyncEngine) -> OutboxWorker:
    """Create an OutboxWorker with a mocked git service (no polling loop)."""
    w = OutboxWorker(async_engine)
    w._git = AsyncMock()
    return w


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession) -> User:
    """Insert a test user and return it."""
    user = User(**make_user(username=f"worker-test-{uuid4().hex[:8]}"))
    session.add(user)
    await session.flush()
    return user


async def _create_entry(
    session: AsyncSession,
    user: User,
    *,
    repo_status: str = "provisioning",
) -> Entry:
    """Insert a test entry and return it."""
    entry = Entry(
        id=uuid4(),
        repo_name=str(uuid4()),
        created_by=user.id,
        repo_status=repo_status,
    )
    session.add(entry)
    await session.flush()
    return entry


async def _create_outbox_entry(
    session: AsyncSession,
    *,
    operation: str,
    payload: dict,
    status: str = "pending",
    attempts: int = 0,
    aggregate_id: UUID | None = None,
    aggregate_type: str = "entry",
) -> Outbox:
    """Insert an outbox row and return it."""
    outbox = Outbox(
        id=uuid4(),
        aggregate_id=aggregate_id or uuid4(),
        aggregate_type=aggregate_type,
        operation=operation,
        payload=payload,
        status=status,
        attempts=attempts,
    )
    session.add(outbox)
    await session.flush()
    return outbox


# ---------------------------------------------------------------------------
# Test: _handle_create_repo happy path
# ---------------------------------------------------------------------------


class TestHandleCreateRepoHappyPath:
    """Verify that _handle_create_repo calls the 5 git service steps in
    order and then updates the entry to 'ready'."""

    async def test_create_repo_calls_all_steps_and_updates_entry(
        self,
        worker: OutboxWorker,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # -- Arrange: create user + entry in provisioning state
        async with session_factory() as session:
            user = await _create_user(session)
            entry = await _create_entry(session, user, repo_status="provisioning")
            entry_id = entry.id
            user_id = user.id
            await session.commit()

        # Configure mock return values
        worker._git.create_repo = AsyncMock(return_value=42)
        worker._git.setup_webhook = AsyncMock()
        worker._git.commit_files = AsyncMock(return_value="abc123def456")
        worker._git.setup_branch_protection = AsyncMock()
        # read_file is called by ingest_entry -- simulate no content file
        worker._git.read_file = AsyncMock(
            side_effect=RepoNotFoundError("no file")
        )

        payload = {
            "entry_id": str(entry_id),
            "content_format": "markdown",
            "author_username": "test-author",
            "author_id": str(user_id),
        }

        # -- Act
        await worker._handle_create_repo(payload)

        # -- Assert: all 5 git steps were called
        worker._git.create_repo.assert_awaited_once_with(entry_id)
        worker._git.setup_webhook.assert_awaited_once_with(entry_id)
        worker._git.commit_files.assert_awaited_once()
        worker._git.setup_branch_protection.assert_awaited_once_with(entry_id)

        # Verify call order: create_repo -> setup_webhook -> commit_files
        # -> setup_branch_protection (then DB update)
        create_order = worker._git.create_repo.await_args_list
        webhook_order = worker._git.setup_webhook.await_args_list
        commit_order = worker._git.commit_files.await_args_list
        protect_order = worker._git.setup_branch_protection.await_args_list

        assert len(create_order) == 1
        assert len(webhook_order) == 1
        assert len(commit_order) == 1
        assert len(protect_order) == 1

        # Step 5: verify entry is updated to ready in DB
        async with session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == entry_id)
            )
            db_entry = result.scalar_one()
            assert db_entry.repo_status == "ready"
            assert db_entry.forgejo_repo_id == 42
            assert db_entry.current_head_sha == "abc123def456"


# ---------------------------------------------------------------------------
# Test: transient error retry
# ---------------------------------------------------------------------------


class TestTransientErrorRetry:
    """ForgejoUnavailableError should mark the entry for retry with
    backoff, NOT as failed."""

    async def test_transient_error_retries_with_backoff(
        self,
        worker: OutboxWorker,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # -- Arrange
        async with session_factory() as session:
            outbox = await _create_outbox_entry(
                session,
                operation="create_repo",
                payload={"entry_id": str(uuid4())},
                status="processing",
                attempts=0,
            )
            outbox_id = outbox.id
            await session.commit()

        # Make _dispatch raise ForgejoUnavailableError
        worker._git.create_repo = AsyncMock(
            side_effect=ForgejoUnavailableError("Forgejo is down")
        )

        # Build a minimal Outbox object as _process_entry expects
        async with session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.id == outbox_id)
            )
            entry = result.scalar_one()

        # -- Act
        await worker._process_entry(entry)

        # -- Assert: entry is back to pending with incremented attempts and backoff
        async with session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.id == outbox_id)
            )
            updated = result.scalar_one()
            assert updated.status == "pending"
            assert updated.attempts == 1
            assert updated.last_error is not None
            assert "Forgejo is down" in updated.last_error
            assert updated.process_after is not None


# ---------------------------------------------------------------------------
# Test: permanent error after max attempts
# ---------------------------------------------------------------------------


class TestPermanentErrorMaxAttempts:
    """After _MAX_ATTEMPTS permanent failures, the outbox entry should be
    marked 'failed' and the associated entry's repo_status set to 'error'."""

    async def test_permanent_error_marks_failed_and_entry_error(
        self,
        worker: OutboxWorker,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # -- Arrange: create user, entry, and outbox entry at max-1 attempts
        async with session_factory() as session:
            user = await _create_user(session)
            entry = await _create_entry(session, user, repo_status="provisioning")
            entry_id = entry.id

            outbox = await _create_outbox_entry(
                session,
                operation="create_repo",
                payload={"entry_id": str(entry_id)},
                status="processing",
                attempts=_MAX_ATTEMPTS - 1,  # next failure will be the last
                aggregate_id=entry_id,
            )
            outbox_id = outbox.id
            await session.commit()

        # Make _dispatch raise a permanent ForgejoError
        worker._git.create_repo = AsyncMock(
            side_effect=ForgejoError("400 Bad Request: invalid payload")
        )

        # Load the outbox entry for _process_entry
        async with session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.id == outbox_id)
            )
            outbox_obj = result.scalar_one()

        # -- Act
        await worker._process_entry(outbox_obj)

        # -- Assert: outbox is failed
        async with session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.id == outbox_id)
            )
            updated = result.scalar_one()
            assert updated.status == "failed"
            assert updated.attempts == _MAX_ATTEMPTS
            assert updated.last_error is not None
            assert "400 Bad Request" in updated.last_error

            # Entry repo_status should be "error"
            result = await session.execute(
                select(Entry).where(Entry.id == entry_id)
            )
            db_entry = result.scalar_one()
            assert db_entry.repo_status == "error"

    async def test_permanent_error_before_max_retries_stays_pending(
        self,
        worker: OutboxWorker,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A permanent error before max attempts should go back to pending,
        not failed."""
        async with session_factory() as session:
            outbox = await _create_outbox_entry(
                session,
                operation="create_repo",
                payload={"entry_id": str(uuid4())},
                status="processing",
                attempts=1,  # well below max
            )
            outbox_id = outbox.id
            await session.commit()

        worker._git.create_repo = AsyncMock(
            side_effect=ForgejoError("temporary glitch")
        )

        async with session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.id == outbox_id)
            )
            outbox_obj = result.scalar_one()

        await worker._process_entry(outbox_obj)

        async with session_factory() as session:
            result = await session.execute(
                select(Outbox).where(Outbox.id == outbox_id)
            )
            updated = result.scalar_one()
            assert updated.status == "pending"
            assert updated.attempts == 2
            assert updated.process_after is not None


# ---------------------------------------------------------------------------
# Test: _recover_stale_processing
# ---------------------------------------------------------------------------


class TestRecoverStaleProcessing:
    """Entries stuck in 'processing' should be reset to 'pending' on
    worker startup."""

    async def test_processing_entries_reset_to_pending(
        self,
        worker: OutboxWorker,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # -- Arrange: create entries in various statuses
        async with session_factory() as session:
            stale1 = await _create_outbox_entry(
                session,
                operation="create_repo",
                payload={"entry_id": str(uuid4())},
                status="processing",
            )
            stale2 = await _create_outbox_entry(
                session,
                operation="commit_files",
                payload={"entry_id": str(uuid4())},
                status="processing",
            )
            pending = await _create_outbox_entry(
                session,
                operation="create_repo",
                payload={"entry_id": str(uuid4())},
                status="pending",
            )
            completed = await _create_outbox_entry(
                session,
                operation="create_repo",
                payload={"entry_id": str(uuid4())},
                status="completed",
            )
            stale1_id = stale1.id
            stale2_id = stale2.id
            pending_id = pending.id
            completed_id = completed.id
            await session.commit()

        # -- Act
        await worker._recover_stale_processing()

        # -- Assert
        async with session_factory() as session:
            # Stale entries should be reset to pending
            for entry_id in (stale1_id, stale2_id):
                result = await session.execute(
                    select(Outbox).where(Outbox.id == entry_id)
                )
                entry = result.scalar_one()
                assert entry.status == "pending", (
                    f"Expected 'pending' for recovered entry {entry_id}, "
                    f"got '{entry.status}'"
                )
                assert entry.process_after is None

            # Pending entry should remain pending
            result = await session.execute(
                select(Outbox).where(Outbox.id == pending_id)
            )
            assert result.scalar_one().status == "pending"

            # Completed entry should remain completed
            result = await session.execute(
                select(Outbox).where(Outbox.id == completed_id)
            )
            assert result.scalar_one().status == "completed"


# ---------------------------------------------------------------------------
# Test: _handle_recompute_views
# ---------------------------------------------------------------------------


class TestHandleRecomputeViews:
    """Verify that _handle_recompute_views calls ingest_entry for a valid
    entry with a HEAD SHA."""

    async def test_recompute_views_calls_ingest(
        self,
        worker: OutboxWorker,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        # -- Arrange
        async with session_factory() as session:
            user = await _create_user(session)
            entry = await _create_entry(session, user, repo_status="ready")
            entry_id = entry.id
            # Set a HEAD SHA so the worker doesn't skip ingestion
            entry.current_head_sha = "deadbeef" * 5
            await session.flush()
            await session.commit()

        payload = {"entry_id": str(entry_id)}

        with patch(
            "phiacta.core.services.outbox_worker.ingest_entry",
            new_callable=AsyncMock,
        ) as mock_ingest:
            # -- Act
            await worker._handle_recompute_views(payload)

            # -- Assert
            mock_ingest.assert_awaited_once()
            call_args = mock_ingest.await_args
            # First positional arg is the entry object
            assert call_args[0][0].id == entry_id
            # Second positional arg is the SHA
            assert call_args[0][1] == "deadbeef" * 5

    async def test_recompute_views_skips_missing_entry(
        self,
        worker: OutboxWorker,
    ) -> None:
        """Non-existent entry should be a no-op, not an error."""
        payload = {"entry_id": str(uuid4())}

        with patch(
            "phiacta.core.services.outbox_worker.ingest_entry",
            new_callable=AsyncMock,
        ) as mock_ingest:
            await worker._handle_recompute_views(payload)
            mock_ingest.assert_not_awaited()

    async def test_recompute_views_skips_no_head_sha(
        self,
        worker: OutboxWorker,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entry without a current_head_sha should be skipped."""
        async with session_factory() as session:
            user = await _create_user(session)
            entry = await _create_entry(session, user, repo_status="ready")
            entry_id = entry.id
            # current_head_sha defaults to None
            await session.commit()

        payload = {"entry_id": str(entry_id)}

        with patch(
            "phiacta.core.services.outbox_worker.ingest_entry",
            new_callable=AsyncMock,
        ) as mock_ingest:
            await worker._handle_recompute_views(payload)
            mock_ingest.assert_not_awaited()
