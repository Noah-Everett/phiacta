# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Reconciliation service for detecting and repairing Forgejo/DB drift.

Scans all Forgejo repos and re-ingests any whose HEAD SHA doesn't match
``entries.current_head_sha`` in the DB.  This is the "rebuild the DB from
git" capability that the architecture promises.

Critical for: missed webhooks, outbox worker failures, DB restoration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from phiacta.core.repositories.entry_repository import EntryRepository
from phiacta.core.services.git_service import ForgejoUnavailableError, GitService
from phiacta.core.services.ingestion import ingest_entry

logger = logging.getLogger(__name__)

# All entries are reconciled regardless of visibility.


@dataclass
class ReconciliationReport:
    entries_checked: int = 0
    entries_drifted: int = 0
    entries_repaired: int = 0
    entries_errored: int = 0
    entries_skipped: int = 0  # archived/retracted
    orphan_repos: list[str] = field(default_factory=list)  # repo names with no DB entry
    missing_repos: list[UUID] = field(default_factory=list)  # entry IDs with no Forgejo repo
    stuck_provisioning: list[UUID] = field(default_factory=list)
    still_provisioning: list[UUID] = field(default_factory=list)
    errors: list[tuple[UUID, str]] = field(default_factory=list)
    dry_run: bool = False


class ReconciliationService:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        git_service: GitService,
        on_ingest_hooks: list | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._git_service = git_service
        self._on_ingest_hooks = on_ingest_hooks or []

    async def reconcile(
        self,
        *,
        dry_run: bool = False,
        entry_ids: list[UUID] | None = None,
        reingest: bool = False,
    ) -> ReconciliationReport:
        """Detect and repair Forgejo/DB drift."""
        report = ReconciliationReport(dry_run=dry_run)

        # --- Phase 1: Gather state ---
        try:
            forgejo_repos = await self._git_service.list_repos()
        except ForgejoUnavailableError:
            logger.error("Forgejo is unreachable — cannot reconcile")
            raise

        # Filter to UUID-named repos only
        forgejo_map: dict[UUID, str] = {}  # entry_id -> repo_name
        for name in forgejo_repos:
            try:
                eid = UUID(name)
                forgejo_map[eid] = name
            except ValueError:
                pass  # non-UUID repos silently ignored

        # Load all DB entries
        async with self._session_factory() as scan_session:
            repo = EntryRepository(scan_session)
            all_entries = await repo.list_all_for_reconciliation()
            all_db_ids: set[UUID] = set()
            db_map: dict[UUID, _EntrySnapshot] = {}
            for entry in all_entries:
                all_db_ids.add(entry.id)
                db_map[entry.id] = _EntrySnapshot(
                    id=entry.id,
                    repo_name=entry.repo_name,
                    current_head_sha=entry.current_head_sha,
                    repo_status=entry.repo_status,
                    visibility=entry.visibility,
                )

        # --- Phase 2: Detect orphan repos (always uses full DB set) ---
        for eid in forgejo_map:
            if eid not in all_db_ids:
                report.orphan_repos.append(str(eid))

        # Apply entry_ids filter if specified (after orphan detection)
        if entry_ids is not None:
            filter_set = set(entry_ids)
            db_map = {eid: snap for eid, snap in db_map.items() if eid in filter_set}

        # --- Phase 3: Classify each DB entry ---
        for eid, snap in db_map.items():
            report.entries_checked += 1

            # All entries are reconciled regardless of visibility

            in_forgejo = eid in forgejo_map

            # Stuck provisioning: DB says provisioning but repo exists in Forgejo
            if snap.repo_status == "provisioning":
                if not in_forgejo:
                    # Expected state — outbox worker hasn't finished yet
                    report.still_provisioning.append(eid)
                    continue

                # Repo exists — check if it has commits
                forgejo_sha = await self._git_service.get_repo_head_sha(eid)
                if forgejo_sha is None:
                    # Repo exists but no main branch (empty)
                    report.still_provisioning.append(eid)
                    continue

                # Stuck provisioning — repo has content, repair it
                report.entries_drifted += 1
                if dry_run:
                    report.stuck_provisioning.append(eid)
                    continue

                try:
                    await self._repair_entry(eid, forgejo_sha, is_stuck_provisioning=True)
                    report.entries_repaired += 1
                    report.stuck_provisioning.append(eid)
                except Exception as exc:
                    logger.exception("Failed to repair stuck entry %s", eid)
                    report.entries_errored += 1
                    report.errors.append((eid, str(exc)))
                continue

            # Missing repo: DB entry (active/draft) but no Forgejo repo
            if not in_forgejo:
                forgejo_sha = await self._git_service.get_repo_head_sha(eid)
                if forgejo_sha is None:
                    report.missing_repos.append(eid)
                    continue
                # Repo found via direct lookup even though not in list_repos
                # (shouldn't happen, but handle gracefully)
            else:
                forgejo_sha = await self._git_service.get_repo_head_sha(eid)

            if forgejo_sha is None:
                report.missing_repos.append(eid)
                continue

            # Compare SHAs
            if snap.current_head_sha == forgejo_sha and not reingest:
                continue  # up to date

            # Drifted
            report.entries_drifted += 1
            if dry_run:
                continue

            try:
                await self._repair_entry(eid, forgejo_sha, is_stuck_provisioning=False)
                report.entries_repaired += 1
            except Exception as exc:
                logger.exception("Failed to repair entry %s", eid)
                report.entries_errored += 1
                report.errors.append((eid, str(exc)))

        return report

    async def _repair_entry(
        self,
        entry_id: UUID,
        forgejo_sha: str,
        *,
        is_stuck_provisioning: bool,
    ) -> None:
        """Re-ingest a single entry in its own transaction.

        Only updates ``current_head_sha`` AFTER successful ingestion.
        """
        async with self._session_factory() as session:
            repo = EntryRepository(session)
            entry = await repo.get_by_id(entry_id)
            if entry is None:
                raise ValueError(f"Entry {entry_id} not found during repair")

            # Optimistic re-check: webhook may have fixed the drift
            if entry.current_head_sha == forgejo_sha and not is_stuck_provisioning:
                return

            # Re-ingest
            await ingest_entry(
                entry, forgejo_sha, session, self._git_service,
                on_ingest_hooks=self._on_ingest_hooks,
            )

            # Only update SHA after successful ingest
            entry.current_head_sha = forgejo_sha

            if is_stuck_provisioning:
                entry.repo_status = "ready"

            await session.commit()


@dataclass(frozen=True, slots=True)
class _EntrySnapshot:
    """Lightweight snapshot of an entry for drift comparison."""

    id: UUID
    repo_name: str
    current_head_sha: str | None
    repo_status: str
    visibility: str
