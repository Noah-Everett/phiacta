# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Outbox worker: polls the outbox table and dispatches operations to Forgejo.

Usage:
    The worker is started as a background task during FastAPI startup via
    ``start_outbox_worker(engine)``. It periodically polls for pending
    outbox entries and processes them using the ``ForgejoGitService``.

    For the ``create_repo`` operation, the worker executes the full compound
    sequence: create repo -> commit initial files -> setup branch protection
    -> setup webhook.  This is treated as a single atomic outbox entry.

Retry policy:
    - **Transient errors** (Forgejo unreachable, timeouts, 503): retried
      indefinitely with exponential backoff (5s, 10s, 20s, ... capped at 5min).
    - **Permanent errors** (bad payload, 400/404, validation): retried up to
      5 times, then marked as ``failed``.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from phiacta.formats import FORMAT_EXTENSIONS
from phiacta.core.models.outbox import Outbox
from phiacta.core.repositories.entry_repository import EntryRepository
# entry.yaml is no longer generated for new entries
from phiacta.core.services.git_service import (
    AuthorInfo,
    FileContent,
    ForgejoError,
    ForgejoGitService,
    ForgejoUnavailableError,
)
from phiacta.core.services.ingestion import ingest_entry

logger = logging.getLogger(__name__)

# Polling interval in seconds
_POLL_INTERVAL = 5.0

# Max entries to process per poll cycle
_BATCH_SIZE = 10

# Backoff constants
_BACKOFF_BASE = 5.0  # seconds
_BACKOFF_MAX = 300.0  # 5 minutes

# Max retry attempts for permanent errors
_MAX_ATTEMPTS = 5



def _backoff_seconds(attempts: int) -> float:
    """Exponential backoff: 5s, 10s, 20s, 40s, ... capped at 5 minutes."""
    return min(_BACKOFF_BASE * (2 ** attempts), _BACKOFF_MAX)


class OutboxWorker:
    """Processes outbox entries by dispatching to Forgejo."""

    def __init__(self, engine: AsyncEngine, on_ingest_hooks: list | None = None) -> None:
        self._engine = engine
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self._git = ForgejoGitService()
        self._on_ingest_hooks = on_ingest_hooks or []
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the polling loop."""
        # Recover any entries orphaned by a previous crash/restart
        await self._recover_stale_processing()
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Outbox worker started")

    async def _recover_stale_processing(self) -> None:
        """Reset entries stuck in 'processing' from a previous worker instance."""
        async with self._session_factory() as session:
            result = await session.execute(
                update(Outbox)
                .where(Outbox.status == "processing")
                .values(status="pending", process_after=None)
                .returning(Outbox.id)
            )
            rows = result.all()
            await session.commit()
            if rows:
                logger.warning(
                    "Recovered %d orphaned outbox entries from 'processing' → 'pending'",
                    len(rows),
                )

    async def stop(self) -> None:
        """Stop the polling loop and close resources."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._git.close()
        logger.info("Outbox worker stopped")

    async def _poll_loop(self) -> None:
        """Main loop: claim and process pending outbox entries."""
        while self._running:
            try:
                processed = await self._process_batch()
                if processed == 0:
                    await asyncio.sleep(_POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Outbox worker error in poll loop")
                await asyncio.sleep(_POLL_INTERVAL)

    async def _process_batch(self) -> int:
        """Claim and process up to _BATCH_SIZE pending entries.

        Uses SELECT FOR UPDATE SKIP LOCKED so multiple workers can run
        concurrently without processing the same entry.

        Only picks up entries whose ``process_after`` has passed (or is NULL).
        """
        now = datetime.now(UTC)

        async with self._session_factory() as session:
            async with session.begin():
                # Claim entries atomically — skip those still in backoff
                stmt = (
                    select(Outbox)
                    .where(
                        Outbox.status == "pending",
                        (Outbox.process_after <= now) | (Outbox.process_after.is_(None)),
                    )
                    .order_by(Outbox.created_at)
                    .limit(_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
                result = await session.execute(stmt)
                entries = list(result.scalars().all())

                if not entries:
                    return 0

                # Mark as processing
                entry_ids = [e.id for e in entries]
                await session.execute(
                    update(Outbox)
                    .where(Outbox.id.in_(entry_ids))
                    .values(status="processing")
                )

        # Process each entry outside the claiming transaction
        for entry in entries:
            await self._process_entry(entry)

        return len(entries)

    async def _process_entry(self, entry: Outbox) -> None:
        """Process a single outbox entry."""
        async with self._session_factory() as session:
            try:
                await self._dispatch(entry)

                # Mark completed
                await session.execute(
                    update(Outbox)
                    .where(Outbox.id == entry.id)
                    .values(
                        status="completed",
                        processed_at=datetime.now(UTC),
                        attempts=entry.attempts + 1,
                        process_after=None,
                    )
                )
                await session.commit()
                logger.info(
                    "Outbox entry %s (%s) completed", entry.id, entry.operation
                )

            except ForgejoUnavailableError as exc:
                # Transient: retry indefinitely with backoff
                await self._mark_transient_retry(session, entry, str(exc))

            except ForgejoError as exc:
                # Permanent: respect max attempts
                await self._mark_permanent_retry(session, entry, str(exc))

            except Exception as exc:
                logger.exception("Unexpected error processing outbox entry %s", entry.id)
                await self._mark_permanent_retry(session, entry, str(exc))

    async def _mark_transient_retry(
        self, session: AsyncSession, entry: Outbox, error: str
    ) -> None:
        """Transient failure (Forgejo down) — retry with backoff, no attempt limit."""
        new_attempts = entry.attempts + 1
        backoff = _backoff_seconds(new_attempts)
        retry_at = datetime.now(UTC) + timedelta(seconds=backoff)

        await session.execute(
            update(Outbox)
            .where(Outbox.id == entry.id)
            .values(
                status="pending",
                attempts=new_attempts,
                last_error=error[:2000],
                process_after=retry_at,
            )
        )
        await session.commit()

        logger.warning(
            "Outbox entry %s (%s) transient failure, retry in %.0fs: %s",
            entry.id,
            entry.operation,
            backoff,
            error[:200],
        )

    async def _mark_permanent_retry(
        self, session: AsyncSession, entry: Outbox, error: str
    ) -> None:
        """Permanent failure — retry up to _MAX_ATTEMPTS, then fail."""
        new_attempts = entry.attempts + 1
        new_status = "failed" if new_attempts >= _MAX_ATTEMPTS else "pending"
        retry_at = (
            None
            if new_status == "failed"
            else datetime.now(UTC) + timedelta(seconds=_backoff_seconds(new_attempts))
        )

        await session.execute(
            update(Outbox)
            .where(Outbox.id == entry.id)
            .values(
                status=new_status,
                attempts=new_attempts,
                last_error=error[:2000],
                process_after=retry_at,
            )
        )

        # If a create_repo entry permanently failed, mark the entry as error
        if new_status == "failed" and entry.operation == "create_repo":
            entry_id_str = entry.payload.get("entry_id")
            if entry_id_str:
                repo = EntryRepository(session)
                db_entry = await repo.get_by_id(UUID(entry_id_str))
                if db_entry is not None and db_entry.repo_status == "provisioning":
                    db_entry.repo_status = "error"
                    await session.flush()

        await session.commit()

        if new_status == "failed":
            logger.error(
                "Outbox entry %s (%s) failed after %d attempts: %s",
                entry.id,
                entry.operation,
                new_attempts,
                error[:200],
            )
        else:
            logger.warning(
                "Outbox entry %s (%s) retrying (attempt %d/%d): %s",
                entry.id,
                entry.operation,
                new_attempts,
                _MAX_ATTEMPTS,
                error[:200],
            )

    async def _dispatch(self, entry: Outbox) -> None:
        """Route an outbox entry to the correct handler."""
        op = entry.operation
        payload = entry.payload

        if op == "create_repo":
            await self._handle_create_repo(payload)
        elif op == "commit_files":
            await self._handle_commit_files(payload)
        elif op == "create_branch":
            await self._handle_create_branch(payload)
        elif op == "setup_branch_protection":
            entry_id = UUID(payload["entry_id"])
            await self._git.setup_branch_protection(entry_id)
        elif op == "setup_webhook":
            entry_id = UUID(payload["entry_id"])
            await self._git.setup_webhook(entry_id)
        elif op == "rename_branch":
            entry_id = UUID(payload["entry_id"])
            old_name = self._validate_git_ref(payload["old_name"])
            new_name = self._validate_git_ref(payload["new_name"])
            await self._git.rename_branch(entry_id, old_name, new_name)
        elif op == "recompute_views":
            await self._handle_recompute_views(payload)
        else:
            raise ValueError(f"Unknown outbox operation: {op}")

    @staticmethod
    def _sanitize_string(value: str, max_length: int = 500) -> str:
        """Sanitize a string payload field."""
        return value[:max_length].strip()

    _GIT_REF_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,254}$")

    @classmethod
    def _validate_git_ref(cls, ref: str) -> str:
        """Validate a git branch/ref name against safe characters."""
        if not cls._GIT_REF_RE.match(ref):
            raise ValueError(f"Invalid git ref name: {ref!r}")
        if ".." in ref or ref.endswith(".lock") or ref.endswith("/"):
            raise ValueError(f"Invalid git ref name: {ref!r}")
        return ref

    @staticmethod
    def _validate_format(fmt: str) -> str:
        """Validate format against allowed values (from FORMAT_EXTENSIONS)."""
        if fmt not in FORMAT_EXTENSIONS:
            raise ValueError(f"Invalid format: {fmt!r}, must be one of {set(FORMAT_EXTENSIONS)}")
        return fmt

    async def _handle_recompute_views(self, payload: dict) -> None:
        """Re-ingest an entry to recompute all view data.

        Triggered by PATCH /entries/{id} when extension data changes.
        Reads current content from git, reads metadata from DB, and
        calls all on_ingest hooks.
        """
        entry_id = UUID(payload["entry_id"])

        async with self._session_factory() as session:
            repo = EntryRepository(session)
            entry = await repo.get_by_id(entry_id)
            if entry is None or entry.current_head_sha is None:
                logger.warning("recompute_views: entry %s not found or no HEAD SHA", entry_id)
                return

            await ingest_entry(
                entry, entry.current_head_sha, session, self._git,
                on_ingest_hooks=self._on_ingest_hooks,
            )
            await session.commit()

    async def _handle_create_repo(self, payload: dict) -> None:
        """Compound operation: create repo + commit initial files + setup
        branch protection + setup webhook.

        This is the full sequence for provisioning a new entry repository.
        """
        entry_id = UUID(payload["entry_id"])
        content_format = self._validate_format(payload.get("content_format", "markdown"))
        author_username = self._sanitize_string(
            payload.get("author_username", "phiacta-service"), max_length=100
        )
        author_id_str = payload.get("author_id", "service")

        # Optional fields from the creation payload
        content = payload.get("content")
        created_at_str = payload.get("created_at")

        author = AuthorInfo(
            name=author_username,
            email=f"{author_id_str}@phiacta.local",
        )

        # Parse created_at or use now
        try:
            created_at = (
                datetime.fromisoformat(created_at_str)
                if created_at_str
                else datetime.now(UTC)
            )
        except (ValueError, TypeError):
            created_at = datetime.now(UTC)

        # Parse author_id as UUID for entry.yaml generation
        try:
            author_id = UUID(author_id_str)
        except (ValueError, TypeError):
            author_id = entry_id  # fallback

        # Step 1: Create the repository (idempotent — checks if exists)
        repo_id = await self._git.create_repo(entry_id)

        # Step 2: Register webhook BEFORE committing files so the initial
        # push triggers ingestion (populates content_cache, current_head_sha).
        try:
            await self._git.setup_webhook(entry_id)
        except ForgejoError as exc:
            if "422" in str(exc) or "409" in str(exc):
                logger.info("Webhook already exists for %s", entry_id)
            else:
                raise

        # Step 3: Commit initial .phiacta/content.{ext}
        # entry.yaml is no longer generated — git stores content only,
        # DB stores everything else.
        ext = FORMAT_EXTENSIONS.get(content_format, ".md")
        content_text = content if content else ""

        files = [
            FileContent(path=f".phiacta/content{ext}", content=content_text),
        ]
        sha = await self._git.commit_files(
            entry_id, files, author, f"Initial entry: {entry_id}"
        )

        # Step 4: Setup branch protection on main
        try:
            await self._git.setup_branch_protection(entry_id)
        except ForgejoError as exc:
            # Idempotent: if protection already exists, log and continue
            if "422" in str(exc) or "409" in str(exc):
                logger.info("Branch protection already exists for %s", entry_id)
            else:
                raise

        # Step 5: Update entry record with Forgejo state.
        async with self._session_factory() as session:
            repo = EntryRepository(session)
            await repo.update_repo_status(
                entry_id,
                repo_status="ready",
                forgejo_repo_id=repo_id,
                current_head_sha=sha,
            )
            await session.commit()

    async def _handle_commit_files(self, payload: dict) -> None:
        """Commit file changes to an existing repo."""
        entry_id = UUID(payload["entry_id"])
        content = payload["content"]
        fmt = self._validate_format(payload.get("content_format", "markdown"))
        message = self._sanitize_string(
            payload.get("message", "Update entry content"), max_length=200
        )
        author_username = self._sanitize_string(
            payload.get("author_username", "phiacta-service"), max_length=100
        )
        author_id = payload.get("author_id", "service")

        author = AuthorInfo(
            name=author_username,
            email=f"{author_id}@phiacta.local",
        )

        ext = FORMAT_EXTENSIONS.get(fmt, ".md")

        files = [FileContent(path=f".phiacta/content{ext}", content=content)]
        sha = await self._git.commit_files(
            entry_id, files, author, message
        )

        # Update head SHA (via repository so ORM onupdate fires)
        async with self._session_factory() as session:
            repo = EntryRepository(session)
            await repo.update_repo_status(
                entry_id,
                repo_status="ready",
                current_head_sha=sha,
            )
            await session.commit()

    async def _handle_create_branch(self, payload: dict) -> None:
        """Create a branch on an entry repo."""
        entry_id = UUID(payload["entry_id"])
        branch_name = self._validate_git_ref(payload["branch_name"])
        from_ref = self._validate_git_ref(payload.get("from_ref", "main"))
        await self._git.create_branch(entry_id, branch_name, from_ref)


async def start_outbox_worker(
    engine: AsyncEngine, on_ingest_hooks: list | None = None,
) -> OutboxWorker:
    """Create and start an outbox worker. Returns the worker for shutdown."""
    worker = OutboxWorker(engine, on_ingest_hooks=on_ingest_hooks)
    await worker.start()
    return worker
