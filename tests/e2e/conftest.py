# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E test fixtures.

Provides an httpx AsyncClient wired to the real FastAPI app with a test
database. Uses TEST_DATABASE_URL if set (real Postgres), otherwise falls
back to SQLite in-memory for environments without Docker.

The Forgejo-dependent tests are marked with ``@pytest.mark.forgejo`` and
require a running Forgejo instance (FORGEJO_URL env var).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from phiacta.core.api.rate_limit import limiter
from phiacta.config import Settings, get_settings
from phiacta.core.db.session import get_db
from phiacta.main import app
from phiacta.core.models.base import Base

# Import all plugin models so Base.metadata.create_all includes their tables.
from phiacta.extensions.metadata.models import ExtensionMetadata  # noqa: F401
from phiacta.extensions.tags.models import ExtensionTag  # noqa: F401
from phiacta.extensions.references.models import ExtensionReference  # noqa: F401
from phiacta.extensions.types.models import ExtensionType  # noqa: F401
from phiacta.views.search_tsv.models import ViewSearchTsv  # noqa: F401
from phiacta.core.services.git_service import (
    AuthorInfo,
    CommitInfo,
    DiffInfo,
    FileContent,
    FileDiff,
    FileInfo,
    PullRequestInfo,
    RepoNotFoundError,
)
from phiacta.core.services.git_service_dep import get_git_service

# Shared test webhook secret -- webhook tests must use this value.
TEST_WEBHOOK_SECRET = "test-webhook-secret-for-e2e-testing"


class FakeGitService:
    """In-memory GitService stub for E2E tests.

    Stores file contents keyed by ``(entry_id_uuid, file_path)`` and returns
    them from ``read_file``.  Stores directory listings keyed by
    ``(entry_id_uuid, dir_path)`` and returns them from ``list_files``.

    Tests populate ``files`` and/or ``file_listings`` before sending
    requests::

        fake_git = FakeGitService()
        fake_git.files[(entry_uuid, ".phiacta/entry.yaml")] = yaml_bytes
        fake_git.file_listings[(entry_uuid, "")] = [
            {"name": "README.md", "path": "README.md", "type": "file", "size": 512},
        ]
    """

    def __init__(self) -> None:
        self.files: dict[tuple[UUID, str], bytes] = {}
        self.file_listings: dict[tuple[UUID, str], list[dict]] = {}
        self.commits: list[dict] = []
        self._commit_counter: int = 0
        self.commit_history: dict[UUID, list[CommitInfo]] = {}
        self.diffs: dict[tuple[UUID, str, str], DiffInfo] = {}
        self.archived_repos: set[UUID] = set()
        # Pull request support for edit proposals (NEV-126/NEV-162).
        self.pull_requests: dict[UUID, list[dict]] = {}  # entry_id -> list of PR dicts
        self.branches: dict[UUID, dict[str, str]] = {}  # entry_id -> {branch_name: base_sha}
        # (entry_id, branch, path) -> content
        self.branch_files: dict[tuple[UUID, str, str], bytes] = {}
        # Issue support
        self.issues: dict[UUID, list[dict]] = {}
        self._pr_counter: dict[UUID, int] = {}  # entry_id -> next PR number
        # Error injection: set to an exception instance to make the next call raise it.
        self._next_error: Exception | None = None

    def _check_error(self) -> None:
        """Raise the injected error if one is pending, then clear it."""
        if self._next_error is not None:
            err = self._next_error
            self._next_error = None
            raise err

    async def read_file(self, entry_id: UUID, path: str, ref: str = "main") -> bytes:
        """Return the file contents or raise RepoNotFoundError."""
        self._check_error()
        key = (entry_id, path)
        if key not in self.files:
            raise RepoNotFoundError(f"File not found: {path} in repo {entry_id}")
        return self.files[key]

    async def list_files(self, entry_id: UUID, path: str = "", ref: str = "main") -> list[FileInfo]:
        """Return the file listing for a directory, or derive from self.files keys."""
        self._check_error()
        key = (entry_id, path)
        if key in self.file_listings:
            return [FileInfo(**d) for d in self.file_listings[key]]
        # Fallback: derive listing from self.files keys that match the directory.
        prefix = f"{path}/" if path else ""
        result: list[FileInfo] = []
        seen: set[str] = set()
        for (eid, fpath) in self.files:
            if eid != entry_id:
                continue
            if prefix and not fpath.startswith(prefix):
                continue
            relative = fpath[len(prefix):]
            if "/" in relative:
                dirname = relative.split("/")[0]
                if dirname not in seen:
                    seen.add(dirname)
                    result.append(FileInfo(
                        name=dirname,
                        path=f"{prefix}{dirname}" if prefix else dirname,
                        type="dir",
                        size=0,
                    ))
            else:
                if relative and relative not in seen:
                    seen.add(relative)
                    result.append(FileInfo(
                        name=relative,
                        path=fpath,
                        type="file",
                        size=len(self.files[(eid, fpath)]),
                    ))
        return result

    # Remaining protocol methods -- not needed for file-read tests.
    async def create_repo(self, entry_id: UUID) -> int:
        raise NotImplementedError

    async def archive_repo(self, entry_id: UUID) -> None:
        self.archived_repos.add(entry_id)

    async def unarchive_repo(self, entry_id: UUID) -> None:
        self.archived_repos.discard(entry_id)

    async def setup_branch_protection(self, entry_id: UUID) -> None:
        raise NotImplementedError

    async def setup_webhook(self, entry_id: UUID) -> None:
        raise NotImplementedError

    async def commit_files(
        self,
        entry_id: UUID,
        files: list[FileContent],
        author: AuthorInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Store files in memory and return a fake commit SHA.

        Branch-aware: files committed to a non-main branch are stored in
        ``branch_files`` rather than ``files``, so they don't appear on main.
        """
        self._check_error()
        self._commit_counter += 1
        for fc in files:
            raw = fc.content if isinstance(fc.content, bytes) else fc.content.encode()
            if branch == "main":
                self.files[(entry_id, fc.path)] = raw
            else:
                self.branch_files[(entry_id, branch, fc.path)] = raw
        sha = f"fake_sha_{self._commit_counter:04d}"
        self.commits.append({
            "sha": sha, "message": message, "author": author,
            "files": [f.path for f in files], "branch": branch,
        })
        return sha

    async def delete_file(
        self,
        entry_id: UUID,
        path: str,
        author: AuthorInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Remove a file from memory and return a fake commit SHA."""
        key = (entry_id, path)
        if key not in self.files:
            raise RepoNotFoundError(f"File not found: {path} in repo {entry_id}")
        del self.files[key]
        self._commit_counter += 1
        sha = f"fake_sha_{self._commit_counter:04d}"
        self.commits.append({"sha": sha, "message": message, "author": author, "files": [path]})
        return sha

    async def list_commits(
        self,
        entry_id: UUID,
        branch: str = "main",
        limit: int = 50,
        page: int = 1,
    ) -> list[CommitInfo]:
        """Return stored commit history or empty list."""
        all_commits = self.commit_history.get(entry_id, [])
        start = (page - 1) * limit
        return all_commits[start : start + limit]

    async def get_diff(
        self, entry_id: UUID, base: str, head: str
    ) -> DiffInfo:
        """Return stored diff or raise RepoNotFoundError."""
        key = (entry_id, base, head)
        if key not in self.diffs:
            raise RepoNotFoundError(f"Diff not found: {base}...{head} in repo {entry_id}")
        return self.diffs[key]

    async def create_branch(self, entry_id: UUID, name: str, from_ref: str = "main") -> None:
        """Create a branch in memory."""
        if entry_id not in self.branches:
            self.branches[entry_id] = {}
        self.branches[entry_id][name] = from_ref

    async def rename_branch(self, entry_id: UUID, old_name: str, new_name: str) -> None:
        """Rename a branch in memory."""
        repo_branches = self.branches.get(entry_id, {})
        if old_name in repo_branches:
            repo_branches[new_name] = repo_branches.pop(old_name)

    async def list_branches(self, entry_id: UUID, exclude_archived: bool = True) -> list[str]:
        """List branches in memory."""
        repo_branches = self.branches.get(entry_id, {})
        names = list(repo_branches.keys())
        if exclude_archived:
            names = [n for n in names if not n.startswith("archived/")]
        return names

    # ------------------------------------------------------------------
    # Pull request support (NEV-126 / NEV-162)
    # ------------------------------------------------------------------

    async def create_pull_request(
        self,
        entry_id: UUID,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        author_name: str = "",
    ) -> PullRequestInfo:
        """Create a fake pull request and return its info."""
        if entry_id not in self._pr_counter:
            self._pr_counter[entry_id] = 0
        self._pr_counter[entry_id] += 1
        number = self._pr_counter[entry_id]

        now = datetime.now(UTC)
        pr = {
            "number": number,
            "title": title,
            "body": body,
            "state": "open",
            "is_draft": False,
            "merged": False,
            "head_branch": head_branch,
            "base_branch": base_branch,
            "author_name": author_name,
            "created_at": now,
            "updated_at": now,
            "merged_at": None,
            "merge_sha": None,
        }
        if entry_id not in self.pull_requests:
            self.pull_requests[entry_id] = []
        self.pull_requests[entry_id].append(pr)

        return PullRequestInfo(
            number=number,
            title=title,
            body=body,
            state="open",
            is_draft=False,
            head_branch=head_branch,
            base_branch=base_branch,
            author_name=author_name,
            created_at=now,
            updated_at=now,
            merged_at=None,
        )

    async def list_pull_requests(
        self,
        entry_id: UUID,
        state: str | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> list[PullRequestInfo]:
        """List fake pull requests, optionally filtered by state."""
        prs = self.pull_requests.get(entry_id, [])

        # Map internal state to the spec's state enum
        def _effective_state(pr: dict) -> str:
            if pr["state"] == "closed" and pr["merged"]:
                return "merged"
            if pr["state"] == "closed" and not pr["merged"]:
                return "closed"
            return "open"

        if state is not None:
            prs = [pr for pr in prs if _effective_state(pr) == state]

        start = (page - 1) * limit
        page_prs = prs[start: start + limit]

        return [
            PullRequestInfo(
                number=pr["number"],
                title=pr["title"],
                body=pr["body"],
                state=_effective_state(pr),
                is_draft=pr["is_draft"],
                head_branch=pr["head_branch"],
                base_branch=pr["base_branch"],
                author_name=pr["author_name"],
                created_at=pr["created_at"],
                updated_at=pr["updated_at"],
                merged_at=pr["merged_at"],
            )
            for pr in page_prs
        ]

    async def get_pull_request(
        self, entry_id: UUID, number: int
    ) -> PullRequestInfo:
        """Get a single pull request by number, or raise RepoNotFoundError."""
        prs = self.pull_requests.get(entry_id, [])
        for pr in prs:
            if pr["number"] == number:
                # Determine effective state
                if pr["state"] == "closed" and pr["merged"]:
                    eff_state = "merged"
                elif pr["state"] == "closed" and not pr["merged"]:
                    eff_state = "closed"
                else:
                    eff_state = "open"
                return PullRequestInfo(
                    number=pr["number"],
                    title=pr["title"],
                    body=pr["body"],
                    state=eff_state,
                    is_draft=pr["is_draft"],
                    head_branch=pr["head_branch"],
                    base_branch=pr["base_branch"],
                    author_name=pr["author_name"],
                    created_at=pr["created_at"],
                    updated_at=pr["updated_at"],
                    merged_at=pr["merged_at"],
                )
        raise RepoNotFoundError(f"PR #{number} not found in repo {entry_id}")

    async def get_pull_request_diff(
        self, entry_id: UUID, number: int
    ) -> DiffInfo:
        """Get the diff for a pull request.

        Derives the diff from branch_files committed to the PR's head branch.
        """
        prs = self.pull_requests.get(entry_id, [])
        pr = None
        for p in prs:
            if p["number"] == number:
                pr = p
                break
        if pr is None:
            raise RepoNotFoundError(f"PR #{number} not found in repo {entry_id}")

        head_branch = pr["head_branch"]
        files_changed: list[FileDiff] = []
        for (eid, branch, path), content in self.branch_files.items():
            if eid == entry_id and branch == head_branch:
                files_changed.append(FileDiff(
                    path=path,
                    patch=(
                        f"--- a/{path}\n+++ b/{path}\n"
                        f"@@ -0,0 +1 @@\n+{content.decode(errors='replace')}"
                    ),
                    additions=1,
                    deletions=0,
                ))

        return DiffInfo(
            base_sha="base_sha_fake",
            head_sha=f"head_sha_pr_{number}",
            files_changed=files_changed,
        )

    async def merge_pull_request(
        self, entry_id: UUID, number: int, merge_style: str = "merge"
    ) -> str:
        """Merge a fake pull request and return the merge commit SHA."""
        prs = self.pull_requests.get(entry_id, [])
        for pr in prs:
            if pr["number"] == number:
                if pr["state"] == "closed" and pr["merged"]:
                    raise RepoNotFoundError(f"PR #{number} already merged")
                if pr["state"] == "closed" and not pr["merged"]:
                    raise RepoNotFoundError(f"PR #{number} is closed")
                if pr["is_draft"]:
                    raise RepoNotFoundError(f"PR #{number} is a draft")
                pr["state"] = "closed"
                pr["merged"] = True
                pr["merged_at"] = datetime.now(UTC)
                self._commit_counter += 1
                merge_sha = f"merge_sha_{self._commit_counter:04d}"
                pr["merge_sha"] = merge_sha
                pr["updated_at"] = datetime.now(UTC)

                # Move branch files to main
                head_branch = pr["head_branch"]
                for (eid, branch, path), content in list(self.branch_files.items()):
                    if eid == entry_id and branch == head_branch:
                        self.files[(entry_id, path)] = content
                return merge_sha
        raise RepoNotFoundError(f"PR #{number} not found in repo {entry_id}")

    async def close_pull_request(self, entry_id: UUID, number: int) -> None:
        """Close a fake pull request without merging.

        Idempotent: closing an already-closed PR is a no-op.
        Closing a merged PR is also a no-op (merged state is preserved).
        """
        prs = self.pull_requests.get(entry_id, [])
        for pr in prs:
            if pr["number"] == number:
                # Don't overwrite merged state — merged PRs stay merged.
                if pr["merged"]:
                    return
                if pr["state"] != "closed":
                    pr["state"] = "closed"
                    pr["updated_at"] = datetime.now(UTC)
                return
        raise RepoNotFoundError(f"PR #{number} not found in repo {entry_id}")

    # --- Issues (fake) ---

    async def create_issue(
        self, entry_id: UUID, title: str, body: str, author_name: str = "",
    ) -> "IssueInfo":
        from phiacta.core.services.git_service import IssueInfo
        issues = self.issues.setdefault(entry_id, [])  # type: ignore[attr-defined]
        number = len(issues) + 1
        now = datetime.now(UTC)
        info = IssueInfo(
            number=number, title=title, body=body, state="open",
            author_name=author_name, comments_count=0,
            created_at=now, updated_at=now, closed_at=None,
        )
        issues.append({"info": info, "comments": []})
        return info

    async def list_issues(
        self, entry_id: UUID, state: str | None = None,
        limit: int = 50, page: int = 1,
    ) -> list["IssueInfo"]:
        issues = getattr(self, "issues", {}).get(entry_id, [])
        result = [i["info"] for i in issues]
        if state:
            result = [i for i in result if i.state == state]
        return result

    async def get_issue(self, entry_id: UUID, number: int) -> "IssueInfo":
        from phiacta.core.services.git_service import RepoNotFoundError as RNF
        for i in getattr(self, "issues", {}).get(entry_id, []):
            if i["info"].number == number:
                return i["info"]
        raise RNF(f"Issue #{number} not found")

    async def get_issue_comments(self, entry_id: UUID, number: int) -> list:
        for i in getattr(self, "issues", {}).get(entry_id, []):
            if i["info"].number == number:
                return i["comments"]
        return []

    async def create_issue_comment(
        self, entry_id: UUID, number: int, body: str,
    ) -> "IssueCommentInfo":
        from phiacta.core.services.git_service import IssueCommentInfo
        for i in getattr(self, "issues", {}).get(entry_id, []):
            if i["info"].number == number:
                now = datetime.now(UTC)
                comment = IssueCommentInfo(
                    id=len(i["comments"]) + 1, body=body,
                    author_name="test", created_at=now, updated_at=now,
                )
                i["comments"].append(comment)
                return comment
        from phiacta.core.services.git_service import RepoNotFoundError as RNF
        raise RNF(f"Issue #{number} not found")

    async def close_issue(self, entry_id: UUID, number: int) -> None:
        from phiacta.core.services.git_service import IssueInfo, RepoNotFoundError as RNF
        issues = getattr(self, "issues", {}).get(entry_id, [])
        for idx, i in enumerate(issues):
            if i["info"].number == number:
                old = i["info"]
                now = datetime.now(UTC)
                issues[idx]["info"] = IssueInfo(
                    number=old.number, title=old.title, body=old.body,
                    state="closed", author_name=old.author_name,
                    comments_count=old.comments_count,
                    created_at=old.created_at, updated_at=now, closed_at=now,
                )
                return
        raise RNF(f"Issue #{number} not found")

    async def list_repos(self) -> list[str]:
        """Return repo names for all known repos (derived from files keys)."""
        seen: set[str] = set()
        for eid, _path in self.files:
            seen.add(str(eid))
        return list(seen)

    async def get_repo_head_sha(
        self, entry_id: UUID, branch: str = "main"
    ) -> str | None:
        """Return None — FakeGitService does not track HEAD SHAs by default.

        Tests that need reconciliation use ReconciliationFakeGitService
        which overrides this.
        """
        return None

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        pass


# Module-level fake so tests can populate files BEFORE the request.
_fake_git_service = FakeGitService()


def _get_test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest.fixture
async def e2e_engine() -> AsyncIterator[AsyncEngine]:
    """Create an engine for the E2E test database."""
    url = _get_test_database_url()
    engine = create_async_engine(url, echo=False)

    # Enable FK enforcement for SQLite (off by default).
    if url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _connection_record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def e2e_session_factory(
    e2e_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        e2e_engine, class_=AsyncSession, expire_on_commit=False,
    )


@pytest.fixture
async def client(
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    """httpx AsyncClient wired to the FastAPI app with test DB."""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with e2e_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    # Override settings so tests use a known webhook secret and JWT key.
    _test_settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret_key="dev-only-change-me-in-production-32chars!",
        forgejo_webhook_secret=TEST_WEBHOOK_SECRET,
        environment="test",
        enabled_plugins=["metadata", "types", "references", "tags", "search_tsv", "search"],
    )
    app.dependency_overrides[get_settings] = lambda: _test_settings

    # Override git service so ingestion tests don't hit real Forgejo.
    _fake_git_service.files.clear()
    _fake_git_service.file_listings.clear()
    _fake_git_service.commits.clear()
    _fake_git_service._commit_counter = 0
    _fake_git_service.commit_history.clear()
    _fake_git_service.diffs.clear()
    _fake_git_service.archived_repos.clear()
    _fake_git_service.pull_requests.clear()
    _fake_git_service.branches.clear()
    _fake_git_service.branch_files.clear()
    _fake_git_service._pr_counter.clear()
    _fake_git_service.issues.clear()
    _fake_git_service._next_error = None
    app.dependency_overrides[get_git_service] = lambda: _fake_git_service

    # Disable rate limiting during tests.
    limiter.enabled = False

    # Register entry data providers for auto-compose (lifespan doesn't run
    # in tests, so the plugin registry isn't populated).
    _providers = []
    try:
        from phiacta.extensions.metadata.provider import entry_data_provider as _mdp
        _providers.append(_mdp)
    except ImportError:
        pass
    try:
        from phiacta.extensions.types.provider import entry_data_provider as _tp
        _providers.append(_tp)
    except ImportError:
        pass
    try:
        from phiacta.extensions.tags.provider import entry_data_provider as _tagp
        _providers.append(_tagp)
    except ImportError:
        pass
    try:
        from phiacta.extensions.references.provider import entry_data_provider as _refp
        _providers.append(_refp)
    except ImportError:
        pass
    app.state.entry_data_providers = _providers

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    limiter.enabled = True
    app.state.entry_data_providers = []
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def register_user(
    client: httpx.AsyncClient,
    handle: str = "test-user",
    password: str = "TestPassword123!",
) -> dict:
    """Register a user and return the full auth response."""
    resp = await client.post("/v1/auth/register", json={
        "handle": handle,
        "password": password,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth_header(token: str) -> dict[str, str]:
    """Return an Authorization header dict for the given token."""
    return {"Authorization": f"Bearer {token}"}


async def create_entry(
    client: httpx.AsyncClient,
    token: str,
    *,
    title: str = "Test Entry",
    content_format: str = "markdown",
    entry_type: str | None = None,
    summary: str | None = None,
    content: str | None = None,
) -> dict:
    """Create an entry via the API and return the response JSON."""
    body: dict = {"title": title, "content_format": content_format}
    if entry_type is not None:
        body["entry_type"] = entry_type
    if summary is not None:
        body["summary"] = summary
    if content is not None:
        body["content"] = content
    resp = await client.post("/v1/entries", json=body, headers=auth_header(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def set_entry_repo_status(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    repo_status: str,
) -> None:
    """Set an entry's repo_status directly in the DB."""
    from phiacta.core.models.entry import Entry

    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.repo_status = repo_status
        await session.commit()


async def set_entry_status(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    status: str,
) -> None:
    """Set an entry's status directly in the DB."""
    from phiacta.core.models.entry import Entry

    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.status = status
        await session.commit()


@pytest.fixture
def fake_git(client: httpx.AsyncClient) -> FakeGitService:
    """Return the FakeGitService instance wired to the current test client.

    The ``client`` fixture clears files on each test, so this is safe to use
    without manual cleanup. Depend on ``client`` to ensure the override is active.
    """
    return _fake_git_service
