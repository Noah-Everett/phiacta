# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""CLI entry point for the reconciliation command.

Usage::

    python -m phiacta.core.cli.reconcile [--dry-run] [--reingest] [--entry-id UUID ...]

Scans all Forgejo repos and re-ingests any whose HEAD SHA doesn't match
the database.  Run inside the backend container for network access to
both Postgres and Forgejo::

    docker compose exec backend python -m phiacta.core.cli.reconcile
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from uuid import UUID

from phiacta.config import get_settings
from phiacta.core.db.session import get_engine, get_session_factory
from phiacta.core.services.git_service import ForgejoGitService
from phiacta.core.services.reconciliation import ReconciliationReport, ReconciliationService
from phiacta.plugin import PluginRegistry

logger = logging.getLogger("phiacta.core.cli.reconcile")


def _print_report(report: ReconciliationReport) -> None:
    """Print a human-readable reconciliation report to stdout."""
    mode = " (DRY RUN)" if report.dry_run else ""
    print(f"\n=== Reconciliation Report{mode} ===")
    print(f"Entries checked:  {report.entries_checked}")
    print(f"Entries drifted:  {report.entries_drifted}")
    print(f"Entries repaired: {report.entries_repaired}")
    print(f"Entries errored:  {report.entries_errored}")
    print(f"Entries skipped:  {report.entries_skipped} (archived/retracted)")

    if report.stuck_provisioning:
        print(f"\nStuck provisioning (repaired): {len(report.stuck_provisioning)}")
        for eid in report.stuck_provisioning:
            print(f"  - {eid}")

    if report.still_provisioning:
        print(f"\nStill provisioning (waiting for outbox): {len(report.still_provisioning)}")
        for eid in report.still_provisioning:
            print(f"  - {eid}")

    if report.orphan_repos:
        print(f"\nOrphan repos (in Forgejo, not in DB): {len(report.orphan_repos)}")
        for name in report.orphan_repos:
            print(f"  - {name}")

    if report.missing_repos:
        print(f"\nMissing repos (in DB, not in Forgejo): {len(report.missing_repos)}")
        for eid in report.missing_repos:
            print(f"  - {eid}")

    if report.errors:
        print(f"\nErrors ({len(report.errors)}):")
        for eid, msg in report.errors:
            print(f"  - {eid}: {msg[:120]}")

    print()


async def _run(args: argparse.Namespace) -> int:
    """Run the reconciliation and return an exit code."""
    engine = get_engine()
    session_factory = get_session_factory()
    git_service = ForgejoGitService()

    # Load plugins to get on_ingest hooks
    settings = get_settings()
    registry = PluginRegistry(enabled_plugins=settings.enabled_plugins)
    registry.discover()
    registry.resolve_dependencies()
    on_ingest_hooks = registry.get_on_ingest_hooks()

    try:
        entry_ids: list[UUID] | None = None
        if args.entry_id:
            entry_ids = [UUID(eid) for eid in args.entry_id]

        service = ReconciliationService(session_factory, git_service, on_ingest_hooks)
        report = await service.reconcile(
            dry_run=args.dry_run,
            entry_ids=entry_ids,
            reingest=args.reingest,
        )

        _print_report(report)

        if report.entries_errored > 0:
            return 1
        return 0
    finally:
        await git_service.close()
        await engine.dispose()


def main() -> None:
    """Parse arguments and run the reconciliation."""
    parser = argparse.ArgumentParser(
        description="Detect and repair Forgejo/DB drift.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be repaired without making changes.",
    )
    parser.add_argument(
        "--entry-id",
        action="append",
        help="Only reconcile specific entry IDs (can be repeated).",
    )
    parser.add_argument(
        "--reingest",
        action="store_true",
        help="Re-ingest all entries regardless of SHA match. Recomputes search tsvectors.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
