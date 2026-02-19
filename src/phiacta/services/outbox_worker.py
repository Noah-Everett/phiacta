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
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from phiacta.models.outbox import Outbox
from phiacta.services.git_service import (
    AgentInfo,
    FileContent,
    ForgejoError,
    ForgejoGitService,
    ForgejoUnavailableError,
)

logger = logging.getLogger(__name__)

# Polling interval in seconds
_POLL_INTERVAL = 5.0

# Max entries to claim per poll cycle
_BATCH_SIZE = 10


class OutboxWorker:
    """Processes outbox entries by dispatching to Forgejo."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._session_factory = async_sessionmaker(engine, expire_on_commit=False)
        self._git = ForgejoGitService()
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the polling loop."""
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Outbox worker started")

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
        """
        async with self._session_factory() as session:
            async with session.begin():
                # Claim entries atomically
                stmt = (
                    select(Outbox)
                    .where(Outbox.status == "pending")
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
                        processed_at=datetime.now(timezone.utc),
                        attempts=entry.attempts + 1,
                    )
                )
                await session.commit()
                logger.info(
                    "Outbox entry %s (%s) completed", entry.id, entry.operation
                )

            except ForgejoUnavailableError as exc:
                # Transient failure — retry later
                await self._mark_retry(session, entry, str(exc))

            except ForgejoError as exc:
                # Permanent-ish failure
                await self._mark_retry(session, entry, str(exc))

            except Exception as exc:
                logger.exception("Unexpected error processing outbox entry %s", entry.id)
                await self._mark_retry(session, entry, str(exc))

    async def _mark_retry(
        self, session: AsyncSession, entry: Outbox, error: str
    ) -> None:
        """Increment attempts and mark as pending (or failed if exhausted)."""
        new_attempts = entry.attempts + 1
        new_status = "failed" if new_attempts >= entry.max_attempts else "pending"

        await session.execute(
            update(Outbox)
            .where(Outbox.id == entry.id)
            .values(
                status=new_status,
                attempts=new_attempts,
                last_error=error[:2000],
            )
        )
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
                entry.max_attempts,
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
            claim_id = UUID(payload["claim_id"])
            await self._git.setup_branch_protection(claim_id)
        elif op == "setup_webhook":
            claim_id = UUID(payload["claim_id"])
            await self._git.setup_webhook(claim_id)
        elif op == "rename_branch":
            claim_id = UUID(payload["claim_id"])
            old_name = self._validate_git_ref(payload["old_name"])
            new_name = self._validate_git_ref(payload["new_name"])
            await self._git.rename_branch(claim_id, old_name, new_name)
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
        """Validate format against allowed values."""
        allowed = {"markdown", "latex", "plain"}
        if fmt not in allowed:
            raise ValueError(f"Invalid format: {fmt!r}, must be one of {allowed}")
        return fmt

    async def _handle_create_repo(self, payload: dict) -> None:
        """Compound operation: create repo + commit initial files + setup
        branch protection + setup webhook.

        This is the full sequence for provisioning a new claim.
        """
        claim_id = UUID(payload["claim_id"])
        title = self._sanitize_string(payload["title"])
        content = payload["content"]
        fmt = self._validate_format(payload.get("format", "markdown"))
        author_name = self._sanitize_string(
            payload.get("author_name", "phiacta-service"), max_length=100
        )
        author_id = payload.get("author_id", "service")

        author = AgentInfo(
            name=author_name,
            email=f"{author_id}@phiacta.local",
        )

        # Step 1: Create the repository
        repo_id = await self._git.create_repo(claim_id)

        # Step 2: Commit initial files
        ext = {"markdown": ".md", "latex": ".tex", "plain": ".txt"}.get(fmt, ".md")
        files = [
            FileContent(path=f"claim{ext}", content=content),
        ]
        sha = await self._git.commit_files(
            claim_id, files, author, f"Initial claim: {title}"
        )

        # Step 3: Setup branch protection on main
        await self._git.setup_branch_protection(claim_id)

        # Step 4: Register webhook
        await self._git.setup_webhook(claim_id)

        # Step 5: Update claim record with Forgejo state
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    UPDATE claims SET
                        forgejo_repo_id = :repo_id,
                        current_head_sha = :sha,
                        repo_status = 'ready'
                    WHERE id = :claim_id
                """),
                {"repo_id": repo_id, "sha": sha, "claim_id": claim_id},
            )
            await session.commit()

    async def _handle_commit_files(self, payload: dict) -> None:
        """Commit file changes to an existing repo."""
        claim_id = UUID(payload["claim_id"])
        content = payload["content"]
        fmt = self._validate_format(payload.get("format", "markdown"))
        message = self._sanitize_string(
            payload.get("message", "Update claim content"), max_length=200
        )
        author_name = self._sanitize_string(
            payload.get("author_name", "phiacta-service"), max_length=100
        )
        author_id = payload.get("author_id", "service")

        author = AgentInfo(
            name=author_name,
            email=f"{author_id}@phiacta.local",
        )

        ext = {"markdown": ".md", "latex": ".tex", "plain": ".txt"}.get(fmt, ".md")
        files = [FileContent(path=f"claim{ext}", content=content)]
        sha = await self._git.commit_files(
            claim_id, files, author, message
        )

        # Update head SHA
        async with self._session_factory() as session:
            await session.execute(
                text("""
                    UPDATE claims SET current_head_sha = :sha
                    WHERE id = :claim_id
                """),
                {"sha": sha, "claim_id": claim_id},
            )
            await session.commit()

    async def _handle_create_branch(self, payload: dict) -> None:
        """Create a branch on a claim repo."""
        claim_id = UUID(payload["claim_id"])
        branch_name = self._validate_git_ref(payload["branch_name"])
        from_ref = self._validate_git_ref(payload.get("from_ref", "main"))
        await self._git.create_branch(claim_id, branch_name, from_ref)


async def start_outbox_worker(engine: AsyncEngine) -> OutboxWorker:
    """Create and start an outbox worker. Returns the worker for shutdown."""
    worker = OutboxWorker(engine)
    await worker.start()
    return worker
