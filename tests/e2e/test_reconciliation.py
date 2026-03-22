# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for reconciliation service (NEV-164).

Tests the ReconciliationService end-to-end with a real test database
and an extended FakeGitService. Unlike most E2E tests that go through
httpx, reconciliation tests instantiate the service directly with the
e2e_session_factory and FakeGitService.

Drift categories tested:
- SHA mismatch (Forgejo HEAD != DB current_head_sha)
- Stuck provisioning (provisioning in DB but repo exists with commits)
- Still provisioning (provisioning in DB, empty repo)
- Missing repo (DB entry but no Forgejo repo)
- Orphan repo (Forgejo repo but no DB entry)
- Up to date (SHAs match)
- Skipped (archived/retracted entries)

Critical adversarial scenarios:
A. SHA matches after optimistic re-check (race won by webhook)
B. entry.yaml parse fails -> SHA NOT updated
C. Empty Forgejo repo with stuck provisioning
D. Archived entry with SHA drift is NOT re-ingested
E. Forgejo org contains non-entry repos
F. Missing Forgejo repo for ready entry
G. Zero entries and zero repos
H. Dry run does not modify DB
I. Partial failure (one good, one bad)
J. Content cache and refs updated after reconciliation
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.core.models.entry import Entry
from phiacta.core.models.entry_ref import EntryRef
from phiacta.core.services.reconciliation import ReconciliationReport, ReconciliationService
from tests.e2e.conftest import (
    FakeGitService,
    create_entry,
    register_user,
    set_entry_repo_status,
    set_entry_status,
)

# ---------------------------------------------------------------------------
# Extended FakeGitService with reconciliation methods
# ---------------------------------------------------------------------------


class ReconciliationFakeGitService(FakeGitService):
    """FakeGitService extended with list_repos and get_repo_head_sha for
    reconciliation tests.

    ``repos`` maps entry_id (UUID) to the HEAD SHA that Forgejo reports.
    A missing key means the repo does not exist in Forgejo.
    A value of None means the repo exists but has no main branch (empty repo).
    """

    def __init__(self) -> None:
        super().__init__()
        self.repos: dict[UUID, str | None] = {}

    async def list_repos(self) -> list[str]:
        """Return repo names (as strings) for all repos in the Forgejo org."""
        return [str(eid) for eid in self.repos]

    async def get_repo_head_sha(
        self, entry_id: UUID, branch: str = "main"
    ) -> str | None:
        """Return the HEAD SHA for a repo, or None if the repo doesn't exist
        or has no main branch."""
        return self.repos.get(entry_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry_yaml(
    entry_id: UUID,
    *,
    title: str = "Test Entry",
    content_format: str = "markdown",
    author_id: UUID | None = None,
    author_handle: str = "test-user",
    summary: str | None = None,
) -> bytes:
    """Build valid entry.yaml bytes for an entry."""
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
    if summary:
        data["summary"] = summary
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False).encode()


def _make_refs_yaml(refs: list[dict]) -> bytes:
    """Build valid refs.yaml bytes."""
    return yaml.dump(
        {"refs": refs},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).encode()


async def _set_entry_head_sha(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    sha: str | None,
) -> None:
    """Set an entry's current_head_sha directly in the DB."""
    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.current_head_sha = sha
        await session.commit()


async def _get_entry(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
) -> Entry:
    """Load an entry from the DB."""
    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        return result.scalar_one()


async def _get_entry_refs(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    direction: str = "outgoing",
) -> list[EntryRef]:
    """Load entry refs from the DB."""
    async with session_factory() as session:
        if direction == "outgoing":
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_id))
            )
        else:
            result = await session.execute(
                select(EntryRef).where(EntryRef.to_entry_id == UUID(entry_id))
            )
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------


class TestReconciliationHappyPath:
    """Scenario: Normal drift detection and repair."""

    async def test_sha_mismatch_triggers_re_ingestion(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Forgejo HEAD != DB current_head_sha -> entry is re-ingested
        and current_head_sha is updated to match Forgejo."""

        # Create entry via API
        auth = await register_user(client, handle="recon-1")
        token = auth["access_token"]
        user_id = auth["user"]["id"]
        entry_data = await create_entry(client, token, title="Drift Entry")
        entry_id = entry_data["id"]

        # Mark as ready with an old SHA
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        old_sha = "a" * 40
        new_sha = "b" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_id, old_sha)

        # Set up FakeGitService with new SHA and valid entry.yaml
        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = new_sha
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = _make_entry_yaml(
            UUID(entry_id),
            title="Reconciled Title",
            author_id=UUID(user_id),
            author_handle="recon-1",
        )
        fake_git.files[(UUID(entry_id), "README.md")] = b"# Reconciled Content"

        # Run reconciliation
        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        # Verify report
        assert isinstance(report, ReconciliationReport)
        assert report.entries_checked >= 1
        assert report.entries_drifted >= 1
        assert report.entries_repaired >= 1
        assert report.entries_errored == 0
        assert report.dry_run is False

        # Verify DB was updated
        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.current_head_sha == new_sha
        assert entry.title == "Reconciled Title"
        assert entry.content_cache == "# Reconciled Content"

    async def test_up_to_date_entry_not_re_ingested(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: SHAs match -> entry is skipped, no changes made."""

        auth = await register_user(client, handle="recon-2")
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Up To Date")
        entry_id = entry_data["id"]

        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        matching_sha = "c" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_id, matching_sha)

        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = matching_sha

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert report.entries_checked >= 1
        assert report.entries_drifted == 0
        assert report.entries_repaired == 0

        # DB unchanged
        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.current_head_sha == matching_sha
        assert entry.title == "Up To Date"


class TestReconciliationContentCacheAndRefs:
    """Scenario (J): Full re-ingest updates content_cache and entry_refs."""

    async def test_content_cache_and_refs_updated_after_reconciliation(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario J: After reconciliation, content_cache and refs must reflect
        the current git state, not stale DB values."""

        # Create two entries -- one will reference the other
        auth = await register_user(client, handle="recon-j")
        token = auth["access_token"]
        user_id = auth["user"]["id"]

        entry_a_data = await create_entry(client, token, title="Entry A")
        entry_a_id = entry_a_data["id"]
        entry_b_data = await create_entry(client, token, title="Entry B")
        entry_b_id = entry_b_data["id"]

        # Mark both as ready
        for eid in [entry_a_id, entry_b_id]:
            await set_entry_repo_status(e2e_session_factory, eid, "ready")

        old_sha = "d" * 40
        new_sha = "e" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_a_id, old_sha)
        await _set_entry_head_sha(e2e_session_factory, entry_b_id, "f" * 40)

        # Set up Forgejo state for entry A: new SHA with content and refs
        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_a_id)] = new_sha
        fake_git.repos[UUID(entry_b_id)] = "f" * 40  # up to date

        fake_git.files[(UUID(entry_a_id), ".phiacta/entry.yaml")] = _make_entry_yaml(
            UUID(entry_a_id),
            title="Entry A Reconciled",
            author_id=UUID(user_id),
            author_handle="recon-j",
            summary="Updated via reconciliation",
        )
        fake_git.files[(UUID(entry_a_id), "README.md")] = b"# Entry A Content Updated"
        fake_git.files[(UUID(entry_a_id), ".phiacta/refs.yaml")] = _make_refs_yaml([
            {
                "rel": "evidence",
                "target": {"entry_id": f"ent_{entry_b_id}"},
                "note": "Added during reconciliation",
            },
        ])

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert report.entries_repaired >= 1

        # Verify content_cache updated
        entry_a = await _get_entry(e2e_session_factory, entry_a_id)
        assert entry_a.content_cache == "# Entry A Content Updated"
        assert entry_a.summary == "Updated via reconciliation"

        # Verify refs updated
        refs = await _get_entry_refs(e2e_session_factory, entry_a_id, "outgoing")
        assert len(refs) == 1
        assert refs[0].to_entry_id == UUID(entry_b_id)
        assert refs[0].rel == "evidence"
        assert refs[0].note == "Added during reconciliation"


class TestReconciliationProvisioningStates:
    """Tests for stuck and still-provisioning entries."""

    async def test_stuck_provisioning_gets_repaired(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Entry has repo_status=provisioning but Forgejo repo
        exists with commits -> re-ingest and set repo_status=ready."""

        auth = await register_user(client, handle="recon-stuck")
        token = auth["access_token"]
        user_id = auth["user"]["id"]
        entry_data = await create_entry(client, token, title="Stuck Entry")
        entry_id = entry_data["id"]

        # Entry is still in provisioning (default after creation)
        assert entry_data["repo_status"] == "provisioning"

        forgejo_sha = "1" * 40
        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = forgejo_sha
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = _make_entry_yaml(
            UUID(entry_id),
            title="Stuck Entry Fixed",
            author_id=UUID(user_id),
            author_handle="recon-stuck",
        )
        fake_git.files[(UUID(entry_id), "README.md")] = b"# Unstuck"

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert UUID(entry_id) in report.stuck_provisioning
        assert report.entries_repaired >= 1

        # Verify repo_status changed to ready
        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.repo_status == "ready"
        assert entry.current_head_sha == forgejo_sha
        assert entry.title == "Stuck Entry Fixed"

    async def test_still_provisioning_empty_repo_skipped(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (C): Entry has repo_status=provisioning, Forgejo repo exists
        but get_repo_head_sha returns None (empty repo). Classified as
        still_provisioning, not crashed."""

        auth = await register_user(
            client, handle="recon-still"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Still Provisioning")
        entry_id = entry_data["id"]

        fake_git = ReconciliationFakeGitService()
        # Repo exists but has no main branch (empty) -- None value
        fake_git.repos[UUID(entry_id)] = None

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert UUID(entry_id) in report.still_provisioning
        assert report.entries_errored == 0

        # Entry should remain in provisioning state
        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.repo_status == "provisioning"


class TestReconciliationMissingAndOrphanRepos:
    """Tests for missing repos and orphan repos."""

    async def test_missing_repo_for_ready_entry(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (F): Entry exists with repo_status=ready but
        get_repo_head_sha returns None (no Forgejo repo). Classified as
        missing_repo."""

        auth = await register_user(
            client, handle="recon-miss"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Missing Repo Entry")
        entry_id = entry_data["id"]

        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        await _set_entry_head_sha(e2e_session_factory, entry_id, "a" * 40)

        # Forgejo has NO repo for this entry
        fake_git = ReconciliationFakeGitService()
        # repos dict is empty -- no repos at all

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert UUID(entry_id) in report.missing_repos

    async def test_orphan_repo_detected(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario: Forgejo has a UUID-named repo that has no corresponding
        DB entry -> reported as orphan."""

        auth = await register_user(
            client, handle="recon-orph"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Real Entry")
        entry_id = entry_data["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        matching_sha = "a" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_id, matching_sha)

        orphan_id = uuid4()
        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = matching_sha  # real entry, up to date
        fake_git.repos[orphan_id] = "b" * 40  # orphan -- no DB entry

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert str(orphan_id) in report.orphan_repos

    async def test_non_uuid_repos_filtered_out(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (E): Forgejo org contains non-UUID repos (e.g., config repos).
        These are silently filtered out and NOT reported as orphans. Only UUID-named
        repos without DB entries are reported as orphans."""

        auth = await register_user(
            client, handle="recon-nonuuid"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Normal Entry")
        entry_id = entry_data["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        sha = "a" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_id, sha)

        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = sha

        # Simulate non-UUID repos by overriding list_repos to include non-UUID names
        original_list = fake_git.list_repos

        async def list_repos_with_extras() -> list[str]:
            base = await original_list()
            return [*base, "not-a-uuid", "config-repo", ".gitea"]

        fake_git.list_repos = list_repos_with_extras  # type: ignore[assignment]

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        # Non-UUID repos should NOT appear in orphan_repos
        assert "not-a-uuid" not in report.orphan_repos
        assert "config-repo" not in report.orphan_repos
        assert ".gitea" not in report.orphan_repos
        # And no false orphans detected
        assert len(report.orphan_repos) == 0


class TestReconciliationArchivedEntries:
    """Tests for archived/retracted entry handling."""

    async def test_archived_entry_with_drift_not_re_ingested(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (D): Archived entry has SHA drift but is NOT re-ingested.
        Its metadata and refs remain unchanged."""

        auth = await register_user(
            client, handle="recon-arch"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Archived Entry")
        entry_id = entry_data["id"]

        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        old_sha = "a" * 40
        new_sha = "b" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_id, old_sha)

        # Archive the entry
        await set_entry_status(e2e_session_factory, entry_id, "archived")

        # Forgejo reports different SHA
        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = new_sha
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = _make_entry_yaml(
            UUID(entry_id), title="Should NOT Be Ingested"
        )

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert report.entries_skipped >= 1
        assert report.entries_repaired == 0

        # Verify DB NOT updated
        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.current_head_sha == old_sha
        assert entry.title == "Archived Entry"

    async def test_retracted_entry_skipped(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Retracted entries are also skipped, same as archived."""

        auth = await register_user(
            client, handle="recon-retract"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Retracted Entry")
        entry_id = entry_data["id"]

        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        await _set_entry_head_sha(e2e_session_factory, entry_id, "a" * 40)
        await set_entry_status(e2e_session_factory, entry_id, "retracted")

        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = "b" * 40

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert report.entries_skipped >= 1

        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.current_head_sha == "a" * 40


class TestReconciliationDryRun:
    """Tests for dry-run mode."""

    async def test_dry_run_does_not_modify_db(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (H): Dry run detects drift but does NOT update the DB."""

        auth = await register_user(
            client, handle="recon-dry"
        )
        token = auth["access_token"]
        user_id = auth["user"]["id"]
        entry_data = await create_entry(client, token, title="Dry Run Entry")
        entry_id = entry_data["id"]

        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        old_sha = "a" * 40
        new_sha = "b" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_id, old_sha)

        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = new_sha
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = _make_entry_yaml(
            UUID(entry_id),
            title="Dry Run Should Not Apply",
            author_id=UUID(user_id),
            author_handle="recon-dry",
        )

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile(dry_run=True)

        # Report should indicate drift was detected
        assert report.dry_run is True
        assert report.entries_drifted >= 1
        # But no repairs should have been made
        assert report.entries_repaired == 0

        # DB must be UNCHANGED
        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.current_head_sha == old_sha
        assert entry.title == "Dry Run Entry"


class TestReconciliationErrorHandling:
    """Tests for error handling during reconciliation."""

    async def test_entry_yaml_parse_failure_leaves_sha_unchanged(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (B): Malformed YAML causes ingest failure. Verify
        current_head_sha stays at old value and entry appears in errors list.
        Next reconciliation run WILL re-try this entry."""

        auth = await register_user(
            client, handle="recon-bad-yaml"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Bad YAML Entry")
        entry_id = entry_data["id"]

        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        old_sha = "a" * 40
        new_sha = "b" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_id, old_sha)

        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = new_sha
        # Malformed YAML -- not valid
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = b": invalid: yaml: {{"

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        # Entry should appear in errors
        assert report.entries_errored >= 1
        error_ids = [eid for eid, _ in report.errors]
        assert UUID(entry_id) in error_ids

        # SHA must NOT be updated
        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.current_head_sha == old_sha
        assert entry.title == "Bad YAML Entry"  # title also unchanged

    async def test_partial_failure_one_good_one_bad(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (I): Two drifted entries -- one with valid YAML, one with
        malformed YAML. Good one gets repaired, bad one goes to errors.
        Reconciliation continues past the first failure."""

        auth = await register_user(
            client, handle="recon-partial"
        )
        token = auth["access_token"]
        user_id = auth["user"]["id"]

        # Entry with valid YAML
        good_entry = await create_entry(client, token, title="Good Entry")
        good_id = good_entry["id"]

        # Entry with bad YAML
        bad_entry = await create_entry(client, token, title="Bad Entry")
        bad_id = bad_entry["id"]

        for eid in [good_id, bad_id]:
            await set_entry_repo_status(e2e_session_factory, eid, "ready")
            await _set_entry_head_sha(e2e_session_factory, eid, "a" * 40)

        good_new_sha = "b" * 40
        bad_new_sha = "c" * 40

        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(good_id)] = good_new_sha
        fake_git.repos[UUID(bad_id)] = bad_new_sha

        # Good entry -- valid YAML
        fake_git.files[(UUID(good_id), ".phiacta/entry.yaml")] = _make_entry_yaml(
            UUID(good_id),
            title="Good Entry Reconciled",
            author_id=UUID(user_id),
            author_handle="recon-partial",
        )
        fake_git.files[(UUID(good_id), "README.md")] = b"# Good"

        # Bad entry -- malformed YAML
        fake_git.files[(UUID(bad_id), ".phiacta/entry.yaml")] = b"not: valid: {{"

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        # Good entry repaired
        assert report.entries_repaired >= 1
        good = await _get_entry(e2e_session_factory, good_id)
        assert good.current_head_sha == good_new_sha
        assert good.title == "Good Entry Reconciled"

        # Bad entry errored, SHA unchanged
        assert report.entries_errored >= 1
        error_ids = [eid for eid, _ in report.errors]
        assert UUID(bad_id) in error_ids
        bad = await _get_entry(e2e_session_factory, bad_id)
        assert bad.current_head_sha == "a" * 40
        assert bad.title == "Bad Entry"


class TestReconciliationRaceCondition:
    """Tests for race conditions between webhook and reconciliation."""

    async def test_sha_matches_after_optimistic_recheck(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (A): Entry appeared drifted at scan time, but by the time
        we acquire the row lock and re-check, the webhook has already updated
        the SHA. Verify ingest_entry is NOT called and the entry is counted
        as not-drifted (no repair needed).

        We simulate this by having the DB SHA match Forgejo SHA at the time
        the per-entry transaction runs (i.e., the "scan" saw stale data but
        the re-check inside the lock sees current data)."""

        auth = await register_user(
            client, handle="recon-race"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Race Entry")
        entry_id = entry_data["id"]

        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        # DB SHA already matches Forgejo -- simulates the webhook winning the race
        matching_sha = "a" * 40
        await _set_entry_head_sha(e2e_session_factory, entry_id, matching_sha)

        fake_git = ReconciliationFakeGitService()
        fake_git.repos[UUID(entry_id)] = matching_sha

        # Even though the initial scan might have seen a stale value,
        # after acquiring the lock the re-check should find a match.
        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        # Should not be counted as repaired
        assert report.entries_repaired == 0
        assert report.entries_errored == 0

        entry = await _get_entry(e2e_session_factory, entry_id)
        assert entry.current_head_sha == matching_sha
        assert entry.title == "Race Entry"  # unchanged


class TestReconciliationEmptyState:
    """Tests for edge cases with zero data."""

    async def test_zero_entries_and_zero_repos(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Scenario (G): No entries in DB and no repos in Forgejo.
        Clean exit with a zero-drift report."""

        fake_git = ReconciliationFakeGitService()
        # No repos at all

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert report.entries_checked == 0
        assert report.entries_drifted == 0
        assert report.entries_repaired == 0
        assert report.entries_errored == 0
        assert report.entries_skipped == 0
        assert report.orphan_repos == []
        assert report.missing_repos == []
        assert report.dry_run is False

    async def test_entries_exist_but_no_repos(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Entries exist in DB but Forgejo has zero repos.
        Active entries should be classified as missing_repos."""

        auth = await register_user(
            client, handle="recon-empty"
        )
        token = auth["access_token"]
        entry_data = await create_entry(client, token, title="Lonely Entry")
        entry_id = entry_data["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        await _set_entry_head_sha(e2e_session_factory, entry_id, "a" * 40)

        fake_git = ReconciliationFakeGitService()
        # No repos

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        assert UUID(entry_id) in report.missing_repos


class TestReconciliationEntryIdFilter:
    """Tests for the optional entry_ids filter."""

    async def test_reconcile_specific_entry_ids(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When entry_ids are specified, only those entries are checked.
        Other drifted entries are ignored."""

        auth = await register_user(
            client, handle="recon-filter"
        )
        token = auth["access_token"]
        user_id = auth["user"]["id"]

        # Create two entries, both with drift
        entry_a = await create_entry(client, token, title="Filter A")
        entry_b = await create_entry(client, token, title="Filter B")
        a_id, b_id = entry_a["id"], entry_b["id"]

        for eid in [a_id, b_id]:
            await set_entry_repo_status(e2e_session_factory, eid, "ready")
            await _set_entry_head_sha(e2e_session_factory, eid, "a" * 40)

        fake_git = ReconciliationFakeGitService()
        new_sha_a = "b" * 40
        new_sha_b = "c" * 40
        fake_git.repos[UUID(a_id)] = new_sha_a
        fake_git.repos[UUID(b_id)] = new_sha_b

        for eid, title in [(a_id, "Filter A Reconciled"), (b_id, "Filter B Reconciled")]:
            fake_git.files[(UUID(eid), ".phiacta/entry.yaml")] = _make_entry_yaml(
                UUID(eid),
                title=title,
                author_id=UUID(user_id),
                author_handle="recon-filter",
            )
            fake_git.files[(UUID(eid), "README.md")] = b"# Content"

        # Only reconcile entry A
        service = ReconciliationService(e2e_session_factory, fake_git)
        await service.reconcile(entry_ids=[UUID(a_id)])

        # Entry A should be repaired
        entry_a_db = await _get_entry(e2e_session_factory, a_id)
        assert entry_a_db.current_head_sha == new_sha_a
        assert entry_a_db.title == "Filter A Reconciled"

        # Entry B should NOT be touched
        entry_b_db = await _get_entry(e2e_session_factory, b_id)
        assert entry_b_db.current_head_sha == "a" * 40
        assert entry_b_db.title == "Filter B"


class TestReconciliationReportStructure:
    """Verify the report dataclass is fully populated with correct values."""

    async def test_report_has_all_fields_populated(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Set up a scenario with multiple drift categories and verify
        the report correctly tallies each one."""

        auth = await register_user(
            client, handle="recon-report"
        )
        token = auth["access_token"]
        user_id = auth["user"]["id"]

        # 1. Up-to-date entry
        up_to_date = await create_entry(client, token, title="Up To Date")
        await set_entry_repo_status(e2e_session_factory, up_to_date["id"], "ready")
        await _set_entry_head_sha(e2e_session_factory, up_to_date["id"], "a" * 40)

        # 2. Drifted entry (will be repaired)
        drifted = await create_entry(client, token, title="Drifted")
        await set_entry_repo_status(e2e_session_factory, drifted["id"], "ready")
        await _set_entry_head_sha(e2e_session_factory, drifted["id"], "a" * 40)

        # 3. Archived entry with drift (should be skipped)
        archived = await create_entry(client, token, title="Archived")
        await set_entry_repo_status(e2e_session_factory, archived["id"], "ready")
        await _set_entry_head_sha(e2e_session_factory, archived["id"], "a" * 40)
        await set_entry_status(e2e_session_factory, archived["id"], "archived")

        # 4. Stuck provisioning entry
        stuck = await create_entry(client, token, title="Stuck")
        # stays provisioning

        # Set up Forgejo state
        fake_git = ReconciliationFakeGitService()

        # 1. Up-to-date
        fake_git.repos[UUID(up_to_date["id"])] = "a" * 40

        # 2. Drifted -- new SHA
        fake_git.repos[UUID(drifted["id"])] = "b" * 40
        fake_git.files[(UUID(drifted["id"]), ".phiacta/entry.yaml")] = _make_entry_yaml(
            UUID(drifted["id"]),
            title="Drifted Repaired",
            author_id=UUID(user_id),
            author_handle="recon-report",
        )

        # 3. Archived -- new SHA (but should be skipped)
        fake_git.repos[UUID(archived["id"])] = "c" * 40

        # 4. Stuck provisioning -- has commits
        fake_git.repos[UUID(stuck["id"])] = "d" * 40
        fake_git.files[(UUID(stuck["id"]), ".phiacta/entry.yaml")] = _make_entry_yaml(
            UUID(stuck["id"]),
            title="Stuck Repaired",
            author_id=UUID(user_id),
            author_handle="recon-report",
        )

        # 5. Orphan repo in Forgejo
        orphan_id = uuid4()
        fake_git.repos[orphan_id] = "e" * 40

        service = ReconciliationService(e2e_session_factory, fake_git)
        report = await service.reconcile()

        # Verify comprehensive report
        assert report.entries_checked >= 4  # at least the 4 entries we created
        assert report.entries_drifted >= 1  # at least the drifted entry
        assert report.entries_repaired >= 2  # drifted + stuck
        assert report.entries_skipped >= 1  # archived
        assert str(orphan_id) in report.orphan_repos
        assert UUID(stuck["id"]) in report.stuck_provisioning
        assert report.dry_run is False

        # Verify the drifted entry got repaired
        drifted_db = await _get_entry(e2e_session_factory, drifted["id"])
        assert drifted_db.current_head_sha == "b" * 40
        assert drifted_db.title == "Drifted Repaired"

        # Verify the archived entry was NOT touched
        archived_db = await _get_entry(e2e_session_factory, archived["id"])
        assert archived_db.current_head_sha == "a" * 40
        assert archived_db.title == "Archived"
