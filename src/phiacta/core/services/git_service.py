# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Forgejo git service adapter.

This is the ONLY module that talks to Forgejo. No Forgejo URLs, tokens, or API
details leak into any other file. All Forgejo API calls are isolated here behind
the ``GitService`` protocol.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import httpx

from phiacta.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthorInfo:
    """Git author identity for commit attribution."""

    name: str
    email: str  # "{user_uuid}@phiacta.local"


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    message: str
    author: AuthorInfo
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class FileContent:
    path: str
    content: str | bytes


@dataclass(frozen=True, slots=True)
class FileInfo:
    """A file or directory entry in a repository listing."""

    name: str
    path: str
    type: str  # "file" or "dir"
    size: int


@dataclass(frozen=True, slots=True)
class FileDiff:
    path: str
    patch: str  # unified diff
    additions: int
    deletions: int


@dataclass(frozen=True, slots=True)
class DiffInfo:
    base_sha: str
    head_sha: str
    files_changed: list[FileDiff]


@dataclass(frozen=True, slots=True)
class PullRequestInfo:
    """Metadata for a pull request / edit proposal."""

    number: int
    title: str
    body: str
    state: str  # "open", "closed", "merged"
    is_draft: bool
    head_branch: str
    base_branch: str
    author_name: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssueInfo:
    """Metadata for a Forgejo issue."""

    number: int
    title: str
    body: str
    state: str  # "open", "closed"
    author_name: str
    comments_count: int
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


@dataclass(frozen=True, slots=True)
class IssueCommentInfo:
    """A single comment on an issue."""

    id: int
    body: str
    author_name: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ForgejoError(Exception):
    """Base exception for Forgejo operations."""


class RepoNotFoundError(ForgejoError):
    """Raised when a repository does not exist."""


class ForgejoUnavailableError(ForgejoError):
    """Raised when Forgejo is unreachable."""


# ---------------------------------------------------------------------------
# Protocol (abstract interface)
# ---------------------------------------------------------------------------


class GitService(Protocol):
    """Abstract interface for git operations.

    All Forgejo details are internal to the implementation.  Callers identify
    repositories by ``entry_id`` (UUID).  The adapter resolves this to the
    Forgejo ``{org}/{entry_uuid}`` path internally.
    """

    # --- Repo lifecycle ---

    async def create_repo(self, entry_id: UUID) -> int:
        """Create a new repo for an entry. Returns Forgejo repo ID."""
        ...

    async def archive_repo(self, entry_id: UUID) -> None:
        """Make a repo read-only (for archived/retracted entries)."""
        ...

    async def unarchive_repo(self, entry_id: UUID) -> None:
        """Restore a repo from read-only (for un-archived entries)."""
        ...

    async def setup_branch_protection(self, entry_id: UUID) -> None:
        """Configure branch protection rules on ``main``."""
        ...

    async def setup_webhook(self, entry_id: UUID) -> None:
        """Register the Phiacta webhook on the repo."""
        ...

    # --- Content operations ---

    async def commit_files(
        self,
        entry_id: UUID,
        files: list[FileContent],
        author: AuthorInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Commit one or more files. Returns the new commit SHA."""
        ...

    async def delete_file(
        self,
        entry_id: UUID,
        path: str,
        author: AuthorInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Delete a file and commit. Returns the new commit SHA."""
        ...

    async def read_file(self, entry_id: UUID, path: str, ref: str = "main") -> bytes:
        """Read a file's contents at a given ref (branch, tag, or SHA)."""
        ...

    async def list_files(
        self, entry_id: UUID, path: str = "", ref: str = "main"
    ) -> list[FileInfo]:
        """List files and directories at a given path and ref."""
        ...

    async def list_tree_paths(
        self, entry_id: UUID, prefix: str = "", ref: str = "main"
    ) -> list[str]:
        """List all file paths recursively, optionally filtered by prefix."""
        ...

    # --- History ---

    async def list_commits(
        self,
        entry_id: UUID,
        branch: str = "main",
        limit: int = 50,
        page: int = 1,
    ) -> list[CommitInfo]:
        """List commits on a branch, newest first."""
        ...

    async def get_diff(self, entry_id: UUID, base: str, head: str) -> DiffInfo:
        """Get the diff between two refs."""
        ...

    # --- Branches ---

    async def create_branch(
        self, entry_id: UUID, name: str, from_ref: str = "main"
    ) -> None:
        """Create a new branch from a given ref."""
        ...

    async def rename_branch(
        self, entry_id: UUID, old_name: str, new_name: str
    ) -> None:
        """Rename a branch (used for archiving merged proposal branches)."""
        ...

    async def delete_branch(self, entry_id: UUID, name: str) -> None:
        """Delete a branch by name."""
        ...

    async def list_branches(
        self, entry_id: UUID, exclude_archived: bool = True
    ) -> list[str]:
        """List branches. Optionally exclude ``archived/*`` branches."""
        ...

    # --- Pull Requests ---

    async def create_pull_request(
        self,
        entry_id: UUID,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        author_name: str = "",
    ) -> PullRequestInfo:
        """Create a pull request and return its info."""
        ...

    async def list_pull_requests(
        self,
        entry_id: UUID,
        state: str | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> list[PullRequestInfo]:
        """List pull requests, optionally filtered by state."""
        ...

    async def get_pull_request(
        self, entry_id: UUID, number: int
    ) -> PullRequestInfo:
        """Get a single pull request by number."""
        ...

    async def get_pull_request_diff(
        self, entry_id: UUID, number: int
    ) -> DiffInfo:
        """Get the diff for a pull request."""
        ...

    async def merge_pull_request(
        self, entry_id: UUID, number: int, merge_style: str = "merge"
    ) -> str:
        """Merge a pull request. Returns the merge commit SHA."""
        ...

    async def close_pull_request(
        self, entry_id: UUID, number: int
    ) -> None:
        """Close a pull request without merging."""
        ...

    # --- Issues ---

    async def create_issue(
        self,
        entry_id: UUID,
        title: str,
        body: str,
        author_name: str = "",
    ) -> IssueInfo:
        """Create an issue on an entry's repository."""
        ...

    async def list_issues(
        self,
        entry_id: UUID,
        state: str | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> list[IssueInfo]:
        """List issues, optionally filtered by state."""
        ...

    async def get_issue(
        self, entry_id: UUID, number: int
    ) -> IssueInfo:
        """Get a single issue by number."""
        ...

    async def get_issue_comments(
        self, entry_id: UUID, number: int
    ) -> list[IssueCommentInfo]:
        """Get comments on an issue."""
        ...

    async def create_issue_comment(
        self, entry_id: UUID, number: int, body: str
    ) -> IssueCommentInfo:
        """Add a comment to an issue."""
        ...

    async def close_issue(
        self, entry_id: UUID, number: int
    ) -> None:
        """Close an issue."""
        ...

    # --- Reconciliation ---

    async def list_repos(self) -> list[str]:
        """List all repository names in the organisation."""
        ...

    async def get_repo_head_sha(
        self, entry_id: UUID, branch: str = "main"
    ) -> str | None:
        """Get the HEAD SHA for a repo's branch.

        Returns ``None`` if the repo or branch does not exist.
        """
        ...

    async def get_repo_size(self, entry_id: UUID) -> int:
        """Return the repository size in bytes."""
        ...

    # --- Health / Lifecycle ---

    async def health_check(self) -> bool:
        """Returns ``True`` if Forgejo is reachable and responsive."""
        ...

    async def close(self) -> None:
        """Close the underlying HTTP client (if any)."""
        ...


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


def _parse_datetime(value: str | None) -> datetime:
    """Parse an ISO-8601 datetime string returned by Forgejo."""
    if not value:
        return datetime.min
    # Forgejo returns e.g. "2026-01-15T12:30:00+00:00"
    return datetime.fromisoformat(value)


def _parse_commit(raw: dict) -> CommitInfo:
    """Convert a Forgejo commit JSON object to ``CommitInfo``."""
    commit_data = raw.get("commit", raw)
    author_data = commit_data.get("author", {})
    return CommitInfo(
        sha=raw.get("sha", commit_data.get("id", "")),
        message=commit_data.get("message", ""),
        author=AuthorInfo(
            name=author_data.get("name", ""),
            email=author_data.get("email", ""),
        ),
        timestamp=_parse_datetime(author_data.get("date")),
    )


def _parse_unified_diff(raw: str) -> list[FileDiff]:
    """Parse a unified diff string into a list of ``FileDiff`` objects.

    Handles the standard ``diff --git a/path b/path`` format returned
    by Forgejo's ``.diff`` endpoint.
    """
    import re

    files: list[FileDiff] = []
    # Split on diff headers
    parts = re.split(r"^diff --git ", raw, flags=re.MULTILINE)

    for part in parts[1:]:  # skip the empty first split
        lines = part.split("\n")
        # First line: "a/path b/path"
        header = lines[0]
        match = re.match(r"a/(.+?) b/(.+)", header)
        path = match.group(2) if match else header

        # Collect the patch text (everything after the header)
        patch_lines = lines[1:]
        patch = "\n".join(patch_lines).rstrip()

        # Count additions and deletions from hunk lines
        additions = sum(1 for l in patch_lines if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in patch_lines if l.startswith("-") and not l.startswith("---"))

        files.append(FileDiff(
            path=path,
            patch=patch,
            additions=additions,
            deletions=deletions,
        ))

    return files


class ForgejoGitService:
    """``GitService`` implementation backed by the Forgejo REST API.

    Parameters
    ----------
    forgejo_url:
        Base URL of the Forgejo instance (e.g. ``http://forgejo:3000``).
        Falls back to ``settings.forgejo_url``.
    """

    def __init__(
        self,
        forgejo_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (forgejo_url or settings.forgejo_url).rstrip("/")
        self._org = settings.forgejo_org
        self._webhook_secret = settings.forgejo_webhook_secret

        self._client = httpx.AsyncClient(
            base_url=f"{self._base_url}/api/v1",
            auth=httpx.BasicAuth(settings.forgejo_admin_user, settings.forgejo_admin_password),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _repo_path(self, entry_id: UUID) -> str:
        """Return the ``owner/repo`` slug for an entry."""
        return f"{self._org}/{entry_id}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | list | None = None,
        params: dict | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        """Send a request and translate HTTP errors to domain exceptions."""
        try:
            resp = await self._client.request(
                method,
                path,
                json=json,
                params=params,
                content=content,
            )
        except httpx.ConnectError as exc:
            raise ForgejoUnavailableError(
                f"Cannot connect to Forgejo at {self._base_url}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ForgejoUnavailableError(
                f"Forgejo request timed out: {method} {path}"
            ) from exc

        if resp.status_code == 404:
            raise RepoNotFoundError(f"Not found: {method} {path}")
        if resp.status_code == 503:
            raise ForgejoUnavailableError("Forgejo returned 503 Service Unavailable")
        if resp.status_code >= 400:
            detail = resp.text[:500] if resp.text else str(resp.status_code)
            raise ForgejoError(
                f"Forgejo API error {resp.status_code} on {method} {path}: {detail}"
            )
        return resp

    async def _paginate(
        self,
        path: str,
        *,
        params: dict | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> list[dict]:
        """Fetch a single page of results from a paginated Forgejo endpoint.

        Forgejo uses ``page`` and ``limit`` query parameters.
        """
        params = dict(params or {})
        params["page"] = page
        params["limit"] = min(limit, 50)  # Forgejo caps at 50 per page
        resp = await self._request("GET", path, params=params)
        return resp.json()

    async def _paginate_all(
        self,
        path: str,
        *,
        params: dict | None = None,
    ) -> list[dict]:
        """Fetch *all* pages from a paginated Forgejo endpoint."""
        results: list[dict] = []
        page = 1
        while True:
            batch = await self._paginate(path, params=params, limit=50, page=page)
            results.extend(batch)
            if len(batch) < 50:
                break
            page += 1
        return results

    # ------------------------------------------------------------------
    # Repo lifecycle
    # ------------------------------------------------------------------

    async def create_repo(self, entry_id: UUID) -> int:
        """Create a new repo under the organisation for *entry_id*.

        Idempotent: if the repo already exists, its ID is returned without
        creating a duplicate.
        """
        repo_name = str(entry_id)

        # Check whether the repo already exists.
        try:
            resp = await self._request("GET", f"/repos/{self._repo_path(entry_id)}")
            existing = resp.json()
            logger.info("Repo %s/%s already exists (id=%s)", self._org, repo_name, existing["id"])
            return existing["id"]
        except RepoNotFoundError:
            pass  # expected — proceed with creation

        resp = await self._request(
            "POST",
            f"/orgs/{self._org}/repos",
            json={
                "name": repo_name,
                "description": f"Entry {entry_id}",
                "private": True,
                "auto_init": False,
                "default_branch": "main",
            },
        )
        repo_data = resp.json()
        repo_id: int = repo_data["id"]
        logger.info("Created repo %s/%s (id=%d)", self._org, repo_name, repo_id)
        return repo_id

    async def archive_repo(self, entry_id: UUID) -> None:
        """Make a repo read-only by setting its ``archived`` flag."""
        await self._request(
            "PATCH",
            f"/repos/{self._repo_path(entry_id)}",
            json={"archived": True},
        )
        logger.info("Archived repo %s", self._repo_path(entry_id))

    async def unarchive_repo(self, entry_id: UUID) -> None:
        """Restore a repo from read-only by clearing the ``archived`` flag."""
        await self._request(
            "PATCH",
            f"/repos/{self._repo_path(entry_id)}",
            json={"archived": False},
        )
        logger.info("Unarchived repo %s", self._repo_path(entry_id))

    async def setup_branch_protection(self, entry_id: UUID) -> None:
        """Configure branch protection on ``main``.

        Rules:
        - No force pushes
        - No branch deletion
        - Only the service account (admin) can push to main (file writes + PR merges)
        """
        repo = self._repo_path(entry_id)
        settings = get_settings()
        await self._request(
            "POST",
            f"/repos/{repo}/branch_protections",
            json={
                "branch_name": "main",
                "enable_push": True,
                "enable_push_whitelist": True,
                "push_whitelist_usernames": [settings.forgejo_admin_user],
                "enable_force_push": False,
                "enable_force_push_whitelist": False,
                "enable_merge_whitelist": False,
                "enable_status_check": False,
                "enable_approvals_whitelist": False,
                "block_on_rejected_reviews": False,
                "block_on_outdated_branch": False,
                "dismiss_stale_approvals": False,
                "require_signed_commits": False,
                "protected_file_patterns": "",
                "unprotected_file_patterns": "",
            },
        )
        logger.info("Branch protection configured on %s/main", repo)

    async def setup_webhook(self, entry_id: UUID) -> None:
        """Register the Phiacta push webhook on the repo."""
        callback_url = get_settings().webhook_callback_url

        repo = self._repo_path(entry_id)
        await self._request(
            "POST",
            f"/repos/{repo}/hooks",
            json={
                "type": "forgejo",
                "active": True,
                "config": {
                    "url": callback_url,
                    "content_type": "json",
                    "secret": self._webhook_secret,
                },
                "events": ["push"],
            },
        )
        logger.info("Webhook registered on %s", repo)

    # ------------------------------------------------------------------
    # Content operations
    # ------------------------------------------------------------------

    async def commit_files(
        self,
        entry_id: UUID,
        files: list[FileContent],
        author: AuthorInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Commit one or more files atomically via the Forgejo multi-file API.

        Uses ``POST /repos/{owner}/{repo}/contents`` with a ``files``
        array to create or update all files in a single atomic commit.

        Returns the SHA of the created commit.
        """
        if not files:
            return ""

        repo = self._repo_path(entry_id)

        # Get the full file tree in one request to decide create vs update.
        # This replaces N per-file GET requests with a single recursive tree fetch.
        existing_paths: set[str] = set()
        try:
            ref_resp = await self._request(
                "GET", f"/repos/{repo}/git/refs/heads/{branch}",
            )
            ref_data = ref_resp.json()
            if isinstance(ref_data, list):
                ref_data = ref_data[0]
            head_sha = ref_data["object"]["sha"]

            tree_resp = await self._request(
                "GET",
                f"/repos/{repo}/git/trees/{head_sha}",
                params={"recursive": "true"},
            )
            for entry in tree_resp.json().get("tree", []):
                if entry.get("type") == "blob":
                    existing_paths.add(entry["path"])
        except (RepoNotFoundError, KeyError):
            pass  # new repo or empty branch

        # Build file operations
        file_ops = []
        for fc in files:
            raw = fc.content if isinstance(fc.content, bytes) else fc.content.encode()
            encoded = base64.b64encode(raw).decode()
            file_ops.append({
                "operation": "update" if fc.path in existing_paths else "create",
                "path": fc.path,
                "content": encoded,
            })

        resp = await self._request(
            "POST",
            f"/repos/{repo}/contents",
            json={
                "message": message,
                "branch": branch,
                "files": file_ops,
                "author": {
                    "name": author.name,
                    "email": author.email,
                },
                "committer": {
                    "name": "phiacta-service",
                    "email": "service@phiacta.local",
                },
            },
        )

        # Extract the commit SHA from the response
        resp_data = resp.json()
        commit_sha = ""
        resp_files = resp_data.get("files", [])
        if resp_files:
            commit_sha = resp_files[0].get("last_commit_sha", "")

        logger.info(
            "Committed %d file(s) to %s@%s (sha=%s)",
            len(files),
            repo,
            branch,
            commit_sha[:12] if commit_sha else "?",
        )
        return commit_sha

    async def read_file(
        self, entry_id: UUID, path: str, ref: str = "main"
    ) -> bytes:
        """Read a file's raw contents at a given ref."""
        repo = self._repo_path(entry_id)
        resp = await self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref},
        )
        data = resp.json()
        content_b64: str = data.get("content", "")
        return base64.b64decode(content_b64)

    async def list_files(
        self, entry_id: UUID, path: str = "", ref: str = "main"
    ) -> list[FileInfo]:
        """List files and directories at a given path and ref."""
        repo = self._repo_path(entry_id)
        endpoint = f"/repos/{repo}/contents/{path}" if path else f"/repos/{repo}/contents"
        resp = await self._request("GET", endpoint, params={"ref": ref})
        items = resp.json()
        # Forgejo returns a list of entries for directories, or a single object
        # for files.
        if isinstance(items, dict):
            return [FileInfo(
                name=items.get("name", path),
                path=items.get("path", path),
                type=items.get("type", "file"),
                size=items.get("size", 0),
            )]
        return [
            FileInfo(
                name=item["name"],
                path=item.get("path", item["name"]),
                type=item.get("type", "file"),
                size=item.get("size", 0),
            )
            for item in items
        ]

    async def list_tree_paths(
        self, entry_id: UUID, prefix: str = "", ref: str = "main"
    ) -> list[str]:
        """List all file paths recursively via the git tree API.

        Returns blob paths optionally filtered to those starting with *prefix*.
        Uses a single API call regardless of directory depth.
        """
        repo = self._repo_path(entry_id)
        # Resolve ref to a SHA
        ref_resp = await self._request(
            "GET", f"/repos/{repo}/git/refs/heads/{ref}",
        )
        ref_data = ref_resp.json()
        if isinstance(ref_data, list):
            ref_data = ref_data[0]
        head_sha = ref_data["object"]["sha"]

        tree_resp = await self._request(
            "GET",
            f"/repos/{repo}/git/trees/{head_sha}",
            params={"recursive": "true"},
        )
        paths = []
        for entry in tree_resp.json().get("tree", []):
            if entry.get("type") == "blob":
                p = entry["path"]
                if not prefix or p.startswith(prefix):
                    paths.append(p)
        return paths

    async def delete_file(
        self,
        entry_id: UUID,
        path: str,
        author: AuthorInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Delete a file and commit. Returns the new commit SHA.

        Uses ``DELETE /repos/{owner}/{repo}/contents/{filepath}`` which
        requires the file's current blob SHA (obtained via a prior GET).
        """
        repo = self._repo_path(entry_id)

        # Get the file's current SHA (required by Forgejo's delete API).
        resp = await self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            params={"ref": branch},
        )
        file_sha = resp.json().get("sha")

        payload: dict = {
            "message": message,
            "sha": file_sha,
            "branch": branch,
            "author": {
                "name": author.name,
                "email": author.email,
            },
            "committer": {
                "name": "phiacta-service",
                "email": "service@phiacta.local",
            },
        }
        resp = await self._request(
            "DELETE",
            f"/repos/{repo}/contents/{path}",
            json=payload,
        )
        commit_data = resp.json().get("commit", {})
        sha = commit_data.get("sha", "")

        logger.info(
            "Deleted %s from %s@%s (sha=%s)",
            path,
            repo,
            branch,
            sha[:12] if sha else "?",
        )
        return sha

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def list_commits(
        self,
        entry_id: UUID,
        branch: str = "main",
        limit: int = 50,
        page: int = 1,
    ) -> list[CommitInfo]:
        """List commits on a branch, newest first.

        Uses ``GET /repos/{owner}/{repo}/commits`` (the commit log endpoint),
        not ``/git/commits`` which is the low-level git objects endpoint and
        returns 404 for branch-based queries.
        """
        repo = self._repo_path(entry_id)
        raw_list = await self._paginate(
            f"/repos/{repo}/commits",
            params={"sha": branch},
            limit=limit,
            page=page,
        )
        return [_parse_commit(c) for c in raw_list]

    async def _resolve_ref(self, repo: str, ref: str) -> str:
        """Resolve a ref (branch, tag, SHA, or ``{sha}~N`` parent notation) to a SHA.

        Forgejo's compare endpoint does not support the ``~N`` parent-ref
        syntax used by git CLI.  This method resolves ``{sha}~1`` (and
        ``~N`` in general) by fetching the commit and walking up N parents.
        Plain SHAs or branch names are returned unchanged.
        """
        # Detect and handle "{sha}~N" parent-ref syntax.
        if "~" in ref:
            parts = ref.rsplit("~", 1)
            base_ref = parts[0]
            try:
                steps = int(parts[1]) if parts[1] else 1
            except ValueError:
                steps = 1

            # Resolve the base ref first, then walk N parents.
            current_sha = base_ref
            for _ in range(steps):
                resp = await self._request("GET", f"/repos/{repo}/git/commits/{current_sha}")
                data = resp.json()
                parents = data.get("parents", [])
                if not parents:
                    raise RepoNotFoundError(
                        f"Commit {current_sha!r} has no parent — cannot resolve {ref!r}"
                    )
                current_sha = parents[0].get("sha", parents[0].get("url", "")).rsplit("/", 1)[-1]
            return current_sha

        return ref

    async def get_diff(
        self, entry_id: UUID, base: str, head: str
    ) -> DiffInfo:
        """Get the diff between two refs.

        Uses the Forgejo ``GET /repos/{repo}/git/commits/{sha}.diff``
        endpoint which returns the full unified diff as plain text.
        The raw diff is parsed via ``_parse_unified_diff``.
        """
        repo = self._repo_path(entry_id)
        resolved_base = await self._resolve_ref(repo, base)
        resolved_head = await self._resolve_ref(repo, head)

        diff_resp = await self._request(
            "GET", f"/repos/{repo}/git/commits/{resolved_head}.diff",
        )
        raw_diff = diff_resp.text
        files_changed = _parse_unified_diff(raw_diff)

        return DiffInfo(
            base_sha=resolved_base,
            head_sha=resolved_head,
            files_changed=files_changed,
        )

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    async def create_branch(
        self, entry_id: UUID, name: str, from_ref: str = "main"
    ) -> None:
        """Create a new branch from a given ref."""
        repo = self._repo_path(entry_id)
        await self._request(
            "POST",
            f"/repos/{repo}/branches",
            json={
                "new_branch_name": name,
                "old_branch_name": from_ref,
            },
        )
        logger.info("Created branch %s on %s from %s", name, repo, from_ref)

    async def delete_branch(self, entry_id: UUID, name: str) -> None:
        """Delete a branch by name."""
        repo = self._repo_path(entry_id)
        await self._request("DELETE", f"/repos/{repo}/branches/{name}")
        logger.info("Deleted branch %s on %s", name, repo)

    async def rename_branch(
        self, entry_id: UUID, old_name: str, new_name: str
    ) -> None:
        """Rename a branch (used for archiving merged proposal branches)."""
        repo = self._repo_path(entry_id)
        await self._request(
            "PATCH",
            f"/repos/{repo}/branches/{old_name}",
            json={"name": new_name},
        )
        logger.info("Renamed branch %s -> %s on %s", old_name, new_name, repo)

    async def list_branches(
        self, entry_id: UUID, exclude_archived: bool = True
    ) -> list[str]:
        """List branch names, optionally excluding ``archived/*`` branches."""
        repo = self._repo_path(entry_id)
        raw_list = await self._paginate_all(f"/repos/{repo}/branches")
        names = [b["name"] for b in raw_list]
        if exclude_archived:
            names = [n for n in names if not n.startswith("archived/")]
        return names

    # ------------------------------------------------------------------
    # Pull Requests
    # ------------------------------------------------------------------

    def _parse_pull_request(self, raw: dict) -> PullRequestInfo:
        """Convert a Forgejo PR JSON object to ``PullRequestInfo``."""
        # Forgejo uses state="closed" + merged=true for merged PRs.
        merged = raw.get("merged", False)
        raw_state = raw.get("state", "open")
        if raw_state == "closed" and merged:
            state = "merged"
        elif raw_state == "closed":
            state = "closed"
        else:
            state = "open"

        user = raw.get("user", {})
        head = raw.get("head", {})
        base = raw.get("base", {})

        return PullRequestInfo(
            number=raw.get("number", 0),
            title=raw.get("title", ""),
            body=raw.get("body", "") or "",
            state=state,
            is_draft=raw.get("draft", False),
            head_branch=head.get("ref", "") if isinstance(head, dict) else "",
            base_branch=base.get("ref", "") if isinstance(base, dict) else "",
            author_name=user.get("login", "") if isinstance(user, dict) else "",
            created_at=_parse_datetime(raw.get("created_at")),
            updated_at=_parse_datetime(raw.get("updated_at")),
            merged_at=_parse_datetime(raw.get("merged_at")) if raw.get("merged_at") else None,
        )

    async def create_pull_request(
        self,
        entry_id: UUID,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
        author_name: str = "",
    ) -> PullRequestInfo:
        """Create a pull request on a repo."""
        repo = self._repo_path(entry_id)
        resp = await self._request(
            "POST",
            f"/repos/{repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head_branch,
                "base": base_branch,
            },
        )
        pr = self._parse_pull_request(resp.json())
        logger.info("Created PR #%d on %s (%s -> %s)", pr.number, repo, head_branch, base_branch)
        return pr

    async def list_pull_requests(
        self,
        entry_id: UUID,
        state: str | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> list[PullRequestInfo]:
        """List pull requests, optionally filtered by state.

        Forgejo only supports ``state=open|closed|all``.  For
        ``state="merged"`` or ``state="closed"`` (rejected), we
        fetch closed PRs and filter client-side.
        """
        repo = self._repo_path(entry_id)
        params: dict[str, str] = {}

        if state == "open":
            params["state"] = "open"
        elif state in ("closed", "merged"):
            params["state"] = "closed"
        else:
            params["state"] = "all"

        raw_list = await self._paginate(
            f"/repos/{repo}/pulls", params=params, limit=limit, page=page,
        )
        prs = [self._parse_pull_request(r) for r in raw_list]

        # Client-side filter for merged vs closed (rejected).
        if state == "merged":
            prs = [p for p in prs if p.state == "merged"]
        elif state == "closed":
            prs = [p for p in prs if p.state == "closed"]

        return prs

    async def get_pull_request(
        self, entry_id: UUID, number: int,
    ) -> PullRequestInfo:
        """Get a single pull request by number."""
        repo = self._repo_path(entry_id)
        resp = await self._request(
            "GET", f"/repos/{repo}/pulls/{number}",
        )
        return self._parse_pull_request(resp.json())

    async def get_pull_request_diff(
        self, entry_id: UUID, number: int,
    ) -> DiffInfo:
        """Get the diff for a pull request.

        Uses Forgejo's ``GET /repos/{owner}/{repo}/pulls/{number}.diff``
        endpoint which returns the full unified diff across all commits
        in the PR.  The raw diff is parsed into ``FileDiff`` objects.
        """
        repo = self._repo_path(entry_id)

        # Get PR metadata for SHAs.
        pr_resp = await self._request(
            "GET", f"/repos/{repo}/pulls/{number}",
        )
        pr_data = pr_resp.json()
        head_sha = pr_data.get("head", {}).get("sha", "")
        base_sha = pr_data.get("base", {}).get("sha", "")

        # Fetch the full PR diff.
        diff_resp = await self._request(
            "GET", f"/repos/{repo}/pulls/{number}.diff",
        )
        raw_diff = diff_resp.text

        # Parse unified diff into FileDiff objects.
        files_changed = _parse_unified_diff(raw_diff)

        return DiffInfo(
            base_sha=base_sha,
            head_sha=head_sha,
            files_changed=files_changed,
        )

    async def merge_pull_request(
        self, entry_id: UUID, number: int, merge_style: str = "merge",
    ) -> str:
        """Merge a pull request. Returns the merge commit SHA."""
        repo = self._repo_path(entry_id)
        resp = await self._request(
            "POST",
            f"/repos/{repo}/pulls/{number}/merge",
            json={"Do": merge_style},
        )
        # Forgejo may return 204 (no body) on some merge styles.
        sha = ""
        if resp.status_code != 204 and resp.content:
            sha = resp.json().get("sha", "")
        # Fallback: re-fetch the PR detail for the authoritative merge_commit_sha.
        if not sha:
            pr_resp = await self._request(
                "GET", f"/repos/{repo}/pulls/{number}",
            )
            sha = pr_resp.json().get("merge_commit_sha", "")
        logger.info("Merged PR #%d on %s (sha=%s)", number, repo, sha[:12] if sha else "?")
        return sha

    async def close_pull_request(
        self, entry_id: UUID, number: int,
    ) -> None:
        """Close a pull request without merging."""
        repo = self._repo_path(entry_id)
        await self._request(
            "PATCH",
            f"/repos/{repo}/pulls/{number}",
            json={"state": "closed"},
        )
        logger.info("Closed PR #%d on %s", number, repo)

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def _parse_issue(self, raw: dict) -> IssueInfo:
        """Convert a Forgejo issue JSON object to ``IssueInfo``."""
        user = raw.get("user", {})
        return IssueInfo(
            number=raw.get("number", 0),
            title=raw.get("title", ""),
            body=raw.get("body", "") or "",
            state=raw.get("state", "open"),
            author_name=user.get("login", "") if isinstance(user, dict) else "",
            comments_count=raw.get("comments", 0),
            created_at=_parse_datetime(raw.get("created_at")),
            updated_at=_parse_datetime(raw.get("updated_at")),
            closed_at=_parse_datetime(raw.get("closed_at")) if raw.get("closed_at") else None,
        )

    def _parse_issue_comment(self, raw: dict) -> IssueCommentInfo:
        """Convert a Forgejo comment JSON object to ``IssueCommentInfo``."""
        user = raw.get("user", {})
        return IssueCommentInfo(
            id=raw.get("id", 0),
            body=raw.get("body", "") or "",
            author_name=user.get("login", "") if isinstance(user, dict) else "",
            created_at=_parse_datetime(raw.get("created_at")),
            updated_at=_parse_datetime(raw.get("updated_at")),
        )

    async def create_issue(
        self,
        entry_id: UUID,
        title: str,
        body: str,
        author_name: str = "",
    ) -> IssueInfo:
        """Create an issue on an entry's repository."""
        repo = self._repo_path(entry_id)
        resp = await self._request(
            "POST",
            f"/repos/{repo}/issues",
            json={"title": title, "body": body},
        )
        issue = self._parse_issue(resp.json())
        logger.info("Created issue #%d on %s", issue.number, repo)
        return issue

    async def list_issues(
        self,
        entry_id: UUID,
        state: str | None = None,
        limit: int = 50,
        page: int = 1,
    ) -> list[IssueInfo]:
        """List issues, optionally filtered by state."""
        repo = self._repo_path(entry_id)
        params: dict[str, str] = {"type": "issues"}
        if state in ("open", "closed"):
            params["state"] = state
        else:
            params["state"] = "all"

        raw_list = await self._paginate(
            f"/repos/{repo}/issues",
            params=params, limit=limit, page=page,
        )
        return [self._parse_issue(r) for r in raw_list]

    async def get_issue(
        self, entry_id: UUID, number: int,
    ) -> IssueInfo:
        """Get a single issue by number."""
        repo = self._repo_path(entry_id)
        resp = await self._request(
            "GET", f"/repos/{repo}/issues/{number}",
        )
        return self._parse_issue(resp.json())

    async def get_issue_comments(
        self, entry_id: UUID, number: int,
    ) -> list[IssueCommentInfo]:
        """Get comments on an issue."""
        repo = self._repo_path(entry_id)
        raw_list = await self._paginate_all(
            f"/repos/{repo}/issues/{number}/comments",
        )
        return [self._parse_issue_comment(r) for r in raw_list]

    async def create_issue_comment(
        self, entry_id: UUID, number: int, body: str,
    ) -> IssueCommentInfo:
        """Add a comment to an issue."""
        repo = self._repo_path(entry_id)
        resp = await self._request(
            "POST",
            f"/repos/{repo}/issues/{number}/comments",
            json={"body": body},
        )
        comment = self._parse_issue_comment(resp.json())
        logger.info("Added comment #%d to issue #%d on %s", comment.id, number, repo)
        return comment

    async def close_issue(
        self, entry_id: UUID, number: int,
    ) -> None:
        """Close an issue."""
        repo = self._repo_path(entry_id)
        await self._request(
            "PATCH",
            f"/repos/{repo}/issues/{number}",
            json={"state": "closed"},
        )
        logger.info("Closed issue #%d on %s", number, repo)

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    async def list_repos(self) -> list[str]:
        """List all repository names in the organisation."""
        raw_list = await self._paginate_all(f"/orgs/{self._org}/repos")
        return [r["name"] for r in raw_list]

    async def get_repo_head_sha(
        self, entry_id: UUID, branch: str = "main"
    ) -> str | None:
        """Get the HEAD SHA for a repo's branch.

        Returns ``None`` if the repo or branch does not exist.
        """
        try:
            resp = await self._request(
                "GET",
                f"/repos/{self._repo_path(entry_id)}/branches/{branch}",
            )
            data = resp.json()
            commit = data.get("commit", {})
            return commit.get("id") or commit.get("sha")
        except RepoNotFoundError:
            return None

    async def get_repo_size(self, entry_id: UUID) -> int:
        """Return the repository size in bytes."""
        resp = await self._request(
            "GET", f"/repos/{self._repo_path(entry_id)}",
        )
        # Forgejo returns size in KiB
        return resp.json().get("size", 0) * 1024

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Return ``True`` if Forgejo is reachable and responsive."""
        try:
            resp = await self._client.get("/settings/api")
            return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client.

        Should be called during application shutdown.
        """
        await self._client.aclose()
