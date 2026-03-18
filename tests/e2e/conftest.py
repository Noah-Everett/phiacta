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

from phiacta.api.rate_limit import limiter
from phiacta.config import Settings, get_settings
from phiacta.db.session import get_db
from phiacta.main import app
from phiacta.models.base import Base
from phiacta.services.git_service import (
    AgentInfo,
    CommitInfo,
    DiffInfo,
    FileContent,
    FileInfo,
    RepoNotFoundError,
)
from phiacta.services.git_service_dep import get_git_service

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

    async def read_file(self, entry_id: UUID, path: str, ref: str = "main") -> bytes:
        """Return the file contents or raise RepoNotFoundError."""
        key = (entry_id, path)
        if key not in self.files:
            raise RepoNotFoundError(f"File not found: {path} in repo {entry_id}")
        return self.files[key]

    async def list_files(self, entry_id: UUID, path: str = "", ref: str = "main") -> list[FileInfo]:
        """Return the file listing for a directory, or derive from self.files keys."""
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
        author: AgentInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Store files in memory and return a fake commit SHA."""
        self._commit_counter += 1
        for fc in files:
            raw = fc.content if isinstance(fc.content, bytes) else fc.content.encode()
            self.files[(entry_id, fc.path)] = raw
        sha = f"fake_sha_{self._commit_counter:04d}"
        self.commits.append({
            "sha": sha, "message": message, "author": author,
            "files": [f.path for f in files],
        })
        return sha

    async def delete_file(
        self,
        entry_id: UUID,
        path: str,
        author: AgentInfo,
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

    async def create_branch(self, entry_id, name, from_ref="main"):  # type: ignore[override]
        raise NotImplementedError

    async def rename_branch(self, entry_id, old_name, new_name):  # type: ignore[override]
        raise NotImplementedError

    async def list_branches(self, entry_id, exclude_archived=True):  # type: ignore[override]
        raise NotImplementedError

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
    app.dependency_overrides[get_git_service] = lambda: _fake_git_service

    # Disable rate limiting during tests.
    limiter.enabled = False

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    limiter.enabled = True
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def register_agent(
    client: httpx.AsyncClient,
    handle: str = "test-agent",
    email: str = "test@example.com",
    password: str = "TestPassword123!",
) -> dict:
    """Register an agent and return the full auth response."""
    resp = await client.post("/v1/auth/register", json={
        "handle": handle,
        "email": email,
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
) -> dict:
    """Create an entry via the API and return the response JSON."""
    body: dict = {"title": title, "content_format": "markdown"}
    resp = await client.post("/v1/entries", json=body, headers=auth_header(token))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def set_entry_repo_status(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    repo_status: str,
) -> None:
    """Set an entry's repo_status directly in the DB."""
    from phiacta.models.entry import Entry

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
    from phiacta.models.entry import Entry

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
