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
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx

from phiacta.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AgentInfo:
    """Git author identity derived from a Phiacta agent."""

    name: str
    email: str  # "{agent_uuid}@phiacta.local"


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    message: str
    author: AgentInfo
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class FileContent:
    path: str
    content: str | bytes


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
class IssueInfo:
    number: int
    title: str
    body: str
    state: str  # "open", "closed"
    labels: list[str]
    created_by: str  # author display name
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class CommentInfo:
    id: int
    body: str
    created_by: str  # author display name
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PullRequestInfo:
    number: int
    title: str
    body: str
    state: str  # "open", "closed", "merged"
    head_branch: str
    base_branch: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ForgejoError(Exception):
    """Base exception for Forgejo operations."""


class RepoNotFoundError(ForgejoError):
    """Raised when a repository does not exist."""


class MergeConflictError(ForgejoError):
    """Raised when a PR cannot be merged due to conflicts."""

    def __init__(self, message: str, conflicting_files: list[str] | None = None) -> None:
        super().__init__(message)
        self.conflicting_files: list[str] = conflicting_files or []


class ForgejoUnavailableError(ForgejoError):
    """Raised when Forgejo is unreachable."""


# ---------------------------------------------------------------------------
# Protocol (abstract interface)
# ---------------------------------------------------------------------------


class GitService(Protocol):
    """Abstract interface for git operations.

    All Forgejo details are internal to the implementation.  Callers identify
    repositories by ``claim_id`` (UUID).  The adapter resolves this to the
    Forgejo ``{org}/{claim_uuid}`` path internally.
    """

    # --- Repo lifecycle ---

    async def create_repo(self, claim_id: UUID) -> int:
        """Create a new repo for a claim. Returns Forgejo repo ID."""
        ...

    async def archive_repo(self, claim_id: UUID) -> None:
        """Make a repo read-only (for archived/retracted claims)."""
        ...

    async def setup_branch_protection(self, claim_id: UUID) -> None:
        """Configure branch protection rules on ``main``."""
        ...

    async def setup_webhook(self, claim_id: UUID) -> None:
        """Register the Phiacta webhook on the repo."""
        ...

    # --- Content operations ---

    async def commit_files(
        self,
        claim_id: UUID,
        files: list[FileContent],
        author: AgentInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Commit one or more files. Returns the new commit SHA."""
        ...

    async def read_file(self, claim_id: UUID, path: str, ref: str = "main") -> bytes:
        """Read a file's contents at a given ref (branch, tag, or SHA)."""
        ...

    async def list_files(
        self, claim_id: UUID, path: str = "", ref: str = "main"
    ) -> list[str]:
        """List file paths in a directory at a given ref."""
        ...

    # --- History ---

    async def list_commits(
        self,
        claim_id: UUID,
        branch: str = "main",
        limit: int = 50,
        page: int = 1,
    ) -> list[CommitInfo]:
        """List commits on a branch, newest first."""
        ...

    async def get_diff(self, claim_id: UUID, base: str, head: str) -> DiffInfo:
        """Get the diff between two refs."""
        ...

    # --- Branches ---

    async def create_branch(
        self, claim_id: UUID, name: str, from_ref: str = "main"
    ) -> None:
        """Create a new branch from a given ref."""
        ...

    async def rename_branch(
        self, claim_id: UUID, old_name: str, new_name: str
    ) -> None:
        """Rename a branch (used for archiving merged proposal branches)."""
        ...

    async def list_branches(
        self, claim_id: UUID, exclude_archived: bool = True
    ) -> list[str]:
        """List branches. Optionally exclude ``archived/*`` branches."""
        ...

    # --- Pull requests (proposals) ---

    async def create_pull_request(
        self,
        claim_id: UUID,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> PullRequestInfo:
        """Create a PR. Returns PR info including number."""
        ...

    async def merge_pull_request(self, claim_id: UUID, pr_number: int) -> str:
        """Merge a PR. Returns the merge commit SHA.

        Raises ``MergeConflictError`` if not mergeable.
        """
        ...

    async def close_pull_request(self, claim_id: UUID, pr_number: int) -> None:
        """Close a PR without merging (reject proposal)."""
        ...

    async def list_pull_requests(
        self,
        claim_id: UUID,
        state: str = "open",
        limit: int = 50,
        page: int = 1,
    ) -> list[PullRequestInfo]:
        """List PRs by state."""
        ...

    async def get_pull_request(
        self, claim_id: UUID, pr_number: int
    ) -> PullRequestInfo:
        """Get a single PR by number."""
        ...

    # --- Issues ---

    async def create_issue(
        self,
        claim_id: UUID,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> IssueInfo:
        """Create an issue. Returns issue info including number."""
        ...

    async def close_issue(self, claim_id: UUID, issue_number: int) -> None:
        """Close an issue."""
        ...

    async def reopen_issue(self, claim_id: UUID, issue_number: int) -> None:
        """Reopen a closed issue."""
        ...

    async def list_issues(
        self,
        claim_id: UUID,
        state: str = "open",
        limit: int = 50,
        page: int = 1,
    ) -> list[IssueInfo]:
        """List issues by state."""
        ...

    async def get_issue(self, claim_id: UUID, issue_number: int) -> IssueInfo:
        """Get a single issue by number."""
        ...

    # --- Comments (on issues and PRs) ---

    async def add_issue_comment(
        self,
        claim_id: UUID,
        issue_number: int,
        body: str,
        author: AgentInfo,
    ) -> CommentInfo:
        """Add a comment to an issue. Returns comment info."""
        ...

    async def list_issue_comments(
        self,
        claim_id: UUID,
        issue_number: int,
        limit: int = 50,
        page: int = 1,
    ) -> list[CommentInfo]:
        """List comments on an issue."""
        ...

    async def add_pr_comment(
        self,
        claim_id: UUID,
        pr_number: int,
        body: str,
        author: AgentInfo,
    ) -> CommentInfo:
        """Add a comment to a PR. Returns comment info."""
        ...

    async def list_pr_comments(
        self,
        claim_id: UUID,
        pr_number: int,
        limit: int = 50,
        page: int = 1,
    ) -> list[CommentInfo]:
        """List comments on a PR."""
        ...

    # --- Health ---

    async def health_check(self) -> bool:
        """Returns ``True`` if Forgejo is reachable and responsive."""
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
        author=AgentInfo(
            name=author_data.get("name", ""),
            email=author_data.get("email", ""),
        ),
        timestamp=_parse_datetime(author_data.get("date")),
    )


def _parse_issue(raw: dict) -> IssueInfo:
    """Convert a Forgejo issue JSON object to ``IssueInfo``."""
    return IssueInfo(
        number=raw["number"],
        title=raw.get("title", ""),
        body=raw.get("body", "") or "",
        state=raw.get("state", "open"),
        labels=[lbl.get("name", "") for lbl in raw.get("labels", [])],
        created_by=raw.get("user", {}).get("login", ""),
        created_at=_parse_datetime(raw.get("created_at")),
        updated_at=_parse_datetime(raw.get("updated_at")),
    )


def _parse_pr(raw: dict) -> PullRequestInfo:
    """Convert a Forgejo PR JSON object to ``PullRequestInfo``."""
    # Forgejo uses state "open"/"closed" plus a separate merged_at field.
    merged_at = raw.get("merged_at")
    if merged_at:
        state = "merged"
        merged_at_dt = _parse_datetime(merged_at)
    else:
        state = raw.get("state", "open")
        merged_at_dt = None

    return PullRequestInfo(
        number=raw["number"],
        title=raw.get("title", ""),
        body=raw.get("body", "") or "",
        state=state,
        head_branch=raw.get("head", {}).get("ref", ""),
        base_branch=raw.get("base", {}).get("ref", ""),
        created_by=raw.get("user", {}).get("login", ""),
        created_at=_parse_datetime(raw.get("created_at")),
        updated_at=_parse_datetime(raw.get("updated_at")),
        merged_at=merged_at_dt,
    )


def _parse_comment(raw: dict) -> CommentInfo:
    """Convert a Forgejo comment JSON object to ``CommentInfo``."""
    return CommentInfo(
        id=raw["id"],
        body=raw.get("body", "") or "",
        created_by=raw.get("user", {}).get("login", ""),
        created_at=_parse_datetime(raw.get("created_at")),
        updated_at=_parse_datetime(raw.get("updated_at")),
    )


class ForgejoGitService:
    """``GitService`` implementation backed by the Forgejo REST API.

    Parameters
    ----------
    forgejo_url:
        Base URL of the Forgejo instance (e.g. ``http://forgejo:3000``).
        Falls back to ``settings.forgejo_url``.
    token:
        API token for the Forgejo service account.  Falls back to
        ``settings.forgejo_token``.
    """

    def __init__(
        self,
        forgejo_url: str | None = None,
        token: str | None = None,
    ) -> None:
        settings = get_settings()
        self._base_url = (forgejo_url or settings.forgejo_url).rstrip("/")
        self._token = token or settings.forgejo_token
        # Fall back to reading token from a file (written by forgejo-init)
        if not self._token and settings.forgejo_token_file:
            token_path = Path(settings.forgejo_token_file)
            if token_path.is_file():
                self._token = token_path.read_text().strip()
                logger.info("Loaded Forgejo token from %s", token_path)
        self._org = settings.forgejo_org
        self._webhook_secret = settings.forgejo_webhook_secret

        self._client = httpx.AsyncClient(
            base_url=f"{self._base_url}/api/v1",
            headers={
                "Authorization": f"token {self._token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _repo_path(self, claim_id: UUID) -> str:
        """Return the ``owner/repo`` slug for a claim."""
        return f"{self._org}/{claim_id}"

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
        if resp.status_code == 409:
            body = resp.json() if resp.content else {}
            raise MergeConflictError(
                body.get("message", "Conflict"),
                conflicting_files=body.get("conflicting_files", []),
            )
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

    async def create_repo(self, claim_id: UUID) -> int:
        """Create a new repo under the organisation for *claim_id*.

        Idempotent: if the repo already exists, its ID is returned without
        creating a duplicate.
        """
        repo_name = str(claim_id)

        # Check whether the repo already exists.
        try:
            resp = await self._request("GET", f"/repos/{self._repo_path(claim_id)}")
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
                "description": f"Claim {claim_id}",
                "private": True,
                "auto_init": False,
                "default_branch": "main",
            },
        )
        repo_data = resp.json()
        repo_id: int = repo_data["id"]
        logger.info("Created repo %s/%s (id=%d)", self._org, repo_name, repo_id)
        return repo_id

    async def archive_repo(self, claim_id: UUID) -> None:
        """Make a repo read-only by setting its ``archived`` flag."""
        await self._request(
            "PATCH",
            f"/repos/{self._repo_path(claim_id)}",
            json={"archived": True},
        )
        logger.info("Archived repo %s", self._repo_path(claim_id))

    async def setup_branch_protection(self, claim_id: UUID) -> None:
        """Configure branch protection on ``main``.

        Rules:
        - No force pushes
        - No branch deletion
        - Push restricted to the service account (only via API)
        """
        repo = self._repo_path(claim_id)
        await self._request(
            "POST",
            f"/repos/{repo}/branch_protections",
            json={
                "branch_name": "main",
                "enable_push": True,
                "enable_push_whitelist": False,
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

    async def setup_webhook(self, claim_id: UUID) -> None:
        """Register the Phiacta push webhook on the repo."""
        settings = get_settings()
        # Build callback URL.  The webhook handler lives at /webhooks/forgejo on
        # the Phiacta API.  In a Docker Compose deployment the API service is
        # reachable from the Forgejo container as ``http://phiacta-api:8000``.
        # The base URL is constructed from the Forgejo URL's scheme/host pattern
        # but in practice the target is the *API* host.  We use a well-known
        # internal address here; a more robust setup would add a dedicated
        # config setting for the callback URL.
        callback_url = "http://phiacta-api:8000/webhooks/forgejo"

        repo = self._repo_path(claim_id)
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
        claim_id: UUID,
        files: list[FileContent],
        author: AgentInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Commit one or more files via the Forgejo Contents API.

        Uses the ``POST /repos/{owner}/{repo}/contents/{filepath}`` and
        ``PUT /repos/{owner}/{repo}/contents/{filepath}`` endpoints to create
        or update files.  Each file is committed individually (Forgejo does not
        support multi-file atomic commits via its REST API).

        Returns the SHA of the last commit created.
        """
        repo = self._repo_path(claim_id)
        last_sha = ""

        for fc in files:
            raw = fc.content if isinstance(fc.content, bytes) else fc.content.encode()
            encoded = base64.b64encode(raw).decode()

            # Check if the file already exists (to decide create vs update).
            existing_sha: str | None = None
            try:
                resp = await self._request(
                    "GET",
                    f"/repos/{repo}/contents/{fc.path}",
                    params={"ref": branch},
                )
                existing_sha = resp.json().get("sha")
            except RepoNotFoundError:
                pass  # file does not exist yet

            payload: dict = {
                "message": message,
                "content": encoded,
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
            if existing_sha is not None:
                payload["sha"] = existing_sha

            method = "PUT" if existing_sha is not None else "POST"
            resp = await self._request(
                method,
                f"/repos/{repo}/contents/{fc.path}",
                json=payload,
            )
            commit_data = resp.json().get("commit", {})
            last_sha = commit_data.get("sha", last_sha)

        logger.info(
            "Committed %d file(s) to %s@%s (sha=%s)",
            len(files),
            repo,
            branch,
            last_sha[:12] if last_sha else "?",
        )
        return last_sha

    async def read_file(
        self, claim_id: UUID, path: str, ref: str = "main"
    ) -> bytes:
        """Read a file's raw contents at a given ref."""
        repo = self._repo_path(claim_id)
        resp = await self._request(
            "GET",
            f"/repos/{repo}/contents/{path}",
            params={"ref": ref},
        )
        data = resp.json()
        content_b64: str = data.get("content", "")
        return base64.b64decode(content_b64)

    async def list_files(
        self, claim_id: UUID, path: str = "", ref: str = "main"
    ) -> list[str]:
        """List file paths in a directory at a given ref."""
        repo = self._repo_path(claim_id)
        endpoint = f"/repos/{repo}/contents/{path}" if path else f"/repos/{repo}/contents"
        resp = await self._request("GET", endpoint, params={"ref": ref})
        items = resp.json()
        # Forgejo returns a list of entries for directories, or a single object
        # for files.  We only list directories here.
        if isinstance(items, dict):
            # Single file — return its name.
            return [items.get("name", path)]
        return [item["name"] for item in items]

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def list_commits(
        self,
        claim_id: UUID,
        branch: str = "main",
        limit: int = 50,
        page: int = 1,
    ) -> list[CommitInfo]:
        """List commits on a branch, newest first."""
        repo = self._repo_path(claim_id)
        raw_list = await self._paginate(
            f"/repos/{repo}/git/commits",
            params={"sha": branch},
            limit=limit,
            page=page,
        )
        return [_parse_commit(c) for c in raw_list]

    async def get_diff(
        self, claim_id: UUID, base: str, head: str
    ) -> DiffInfo:
        """Get the diff between two refs.

        Uses the Forgejo compare endpoint:
        ``GET /repos/{owner}/{repo}/compare/{base}...{head}``
        """
        repo = self._repo_path(claim_id)
        resp = await self._request(
            "GET",
            f"/repos/{repo}/compare/{base}...{head}",
        )
        data = resp.json()

        files_changed: list[FileDiff] = []
        for f in data.get("files", []):
            files_changed.append(
                FileDiff(
                    path=f.get("filename", ""),
                    patch=f.get("patch", ""),
                    additions=f.get("additions", 0),
                    deletions=f.get("deletions", 0),
                )
            )

        # Extract SHAs from the compare response.
        commits = data.get("commits", [])
        base_sha = commits[0]["sha"] if commits else base
        head_sha = commits[-1]["sha"] if commits else head

        return DiffInfo(
            base_sha=base_sha,
            head_sha=head_sha,
            files_changed=files_changed,
        )

    # ------------------------------------------------------------------
    # Branches
    # ------------------------------------------------------------------

    async def create_branch(
        self, claim_id: UUID, name: str, from_ref: str = "main"
    ) -> None:
        """Create a new branch from a given ref."""
        repo = self._repo_path(claim_id)
        await self._request(
            "POST",
            f"/repos/{repo}/branches",
            json={
                "new_branch_name": name,
                "old_branch_name": from_ref,
            },
        )
        logger.info("Created branch %s on %s from %s", name, repo, from_ref)

    async def rename_branch(
        self, claim_id: UUID, old_name: str, new_name: str
    ) -> None:
        """Rename a branch (used for archiving merged proposal branches)."""
        repo = self._repo_path(claim_id)
        await self._request(
            "PATCH",
            f"/repos/{repo}/branches/{old_name}",
            json={"name": new_name},
        )
        logger.info("Renamed branch %s -> %s on %s", old_name, new_name, repo)

    async def list_branches(
        self, claim_id: UUID, exclude_archived: bool = True
    ) -> list[str]:
        """List branch names, optionally excluding ``archived/*`` branches."""
        repo = self._repo_path(claim_id)
        raw_list = await self._paginate_all(f"/repos/{repo}/branches")
        names = [b["name"] for b in raw_list]
        if exclude_archived:
            names = [n for n in names if not n.startswith("archived/")]
        return names

    # ------------------------------------------------------------------
    # Pull requests (proposals)
    # ------------------------------------------------------------------

    async def create_pull_request(
        self,
        claim_id: UUID,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> PullRequestInfo:
        """Create a pull request. Returns PR info including number."""
        repo = self._repo_path(claim_id)
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
        return _parse_pr(resp.json())

    async def merge_pull_request(self, claim_id: UUID, pr_number: int) -> str:
        """Merge a PR. Returns the merge commit SHA.

        Raises ``MergeConflictError`` if the PR is not mergeable.
        """
        repo = self._repo_path(claim_id)
        resp = await self._request(
            "POST",
            f"/repos/{repo}/pulls/{pr_number}/merge",
            json={
                "Do": "merge",
                "merge_message_field": "",
            },
        )
        # After merging, fetch the PR to get the merge commit SHA.
        pr_resp = await self._request(
            "GET",
            f"/repos/{repo}/pulls/{pr_number}",
        )
        pr_data = pr_resp.json()
        merge_sha: str = pr_data.get("merge_commit_sha", "")
        logger.info("Merged PR #%d on %s (sha=%s)", pr_number, repo, merge_sha[:12])
        return merge_sha

    async def close_pull_request(self, claim_id: UUID, pr_number: int) -> None:
        """Close a PR without merging."""
        repo = self._repo_path(claim_id)
        await self._request(
            "PATCH",
            f"/repos/{repo}/pulls/{pr_number}",
            json={"state": "closed"},
        )
        logger.info("Closed PR #%d on %s", pr_number, repo)

    async def list_pull_requests(
        self,
        claim_id: UUID,
        state: str = "open",
        limit: int = 50,
        page: int = 1,
    ) -> list[PullRequestInfo]:
        """List PRs filtered by state."""
        repo = self._repo_path(claim_id)
        raw_list = await self._paginate(
            f"/repos/{repo}/pulls",
            params={"state": state},
            limit=limit,
            page=page,
        )
        return [_parse_pr(pr) for pr in raw_list]

    async def get_pull_request(
        self, claim_id: UUID, pr_number: int
    ) -> PullRequestInfo:
        """Get a single PR by number."""
        repo = self._repo_path(claim_id)
        resp = await self._request("GET", f"/repos/{repo}/pulls/{pr_number}")
        return _parse_pr(resp.json())

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def create_issue(
        self,
        claim_id: UUID,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> IssueInfo:
        """Create an issue. Returns issue info including number.

        Labels are resolved to Forgejo label IDs by name.  Non-existent labels
        are silently ignored.
        """
        repo = self._repo_path(claim_id)
        payload: dict = {"title": title, "body": body}

        if labels:
            # Resolve label names to IDs.
            label_ids = await self._resolve_label_ids(claim_id, labels)
            if label_ids:
                payload["labels"] = label_ids

        resp = await self._request(
            "POST",
            f"/repos/{repo}/issues",
            json=payload,
        )
        return _parse_issue(resp.json())

    async def close_issue(self, claim_id: UUID, issue_number: int) -> None:
        """Close an issue."""
        repo = self._repo_path(claim_id)
        await self._request(
            "PATCH",
            f"/repos/{repo}/issues/{issue_number}",
            json={"state": "closed"},
        )
        logger.info("Closed issue #%d on %s", issue_number, repo)

    async def reopen_issue(self, claim_id: UUID, issue_number: int) -> None:
        """Reopen a closed issue."""
        repo = self._repo_path(claim_id)
        await self._request(
            "PATCH",
            f"/repos/{repo}/issues/{issue_number}",
            json={"state": "open"},
        )
        logger.info("Reopened issue #%d on %s", issue_number, repo)

    async def list_issues(
        self,
        claim_id: UUID,
        state: str = "open",
        limit: int = 50,
        page: int = 1,
    ) -> list[IssueInfo]:
        """List issues filtered by state."""
        repo = self._repo_path(claim_id)
        raw_list = await self._paginate(
            f"/repos/{repo}/issues",
            params={"state": state, "type": "issues"},
            limit=limit,
            page=page,
        )
        return [_parse_issue(i) for i in raw_list]

    async def get_issue(self, claim_id: UUID, issue_number: int) -> IssueInfo:
        """Get a single issue by number."""
        repo = self._repo_path(claim_id)
        resp = await self._request(
            "GET",
            f"/repos/{repo}/issues/{issue_number}",
        )
        return _parse_issue(resp.json())

    # ------------------------------------------------------------------
    # Comments (issues and PRs)
    # ------------------------------------------------------------------

    async def add_issue_comment(
        self,
        claim_id: UUID,
        issue_number: int,
        body: str,
        author: AgentInfo,
    ) -> CommentInfo:
        """Add a comment to an issue.

        The comment body is prefixed with an authorship line since all
        Forgejo API calls are made by the service account.
        """
        repo = self._repo_path(claim_id)
        attributed_body = f"**{author.name}** ({author.email}):\n\n{body}"
        resp = await self._request(
            "POST",
            f"/repos/{repo}/issues/{issue_number}/comments",
            json={"body": attributed_body},
        )
        return _parse_comment(resp.json())

    async def list_issue_comments(
        self,
        claim_id: UUID,
        issue_number: int,
        limit: int = 50,
        page: int = 1,
    ) -> list[CommentInfo]:
        """List comments on an issue."""
        repo = self._repo_path(claim_id)
        raw_list = await self._paginate(
            f"/repos/{repo}/issues/{issue_number}/comments",
            limit=limit,
            page=page,
        )
        return [_parse_comment(c) for c in raw_list]

    async def add_pr_comment(
        self,
        claim_id: UUID,
        pr_number: int,
        body: str,
        author: AgentInfo,
    ) -> CommentInfo:
        """Add a comment to a PR.

        Forgejo treats PR comments as issue comments (PRs are issues
        internally), so this uses the issues comment endpoint.
        """
        repo = self._repo_path(claim_id)
        attributed_body = f"**{author.name}** ({author.email}):\n\n{body}"
        resp = await self._request(
            "POST",
            f"/repos/{repo}/issues/{pr_number}/comments",
            json={"body": attributed_body},
        )
        return _parse_comment(resp.json())

    async def list_pr_comments(
        self,
        claim_id: UUID,
        pr_number: int,
        limit: int = 50,
        page: int = 1,
    ) -> list[CommentInfo]:
        """List comments on a PR.

        Forgejo treats PR comments as issue comments.
        """
        repo = self._repo_path(claim_id)
        raw_list = await self._paginate(
            f"/repos/{repo}/issues/{pr_number}/comments",
            limit=limit,
            page=page,
        )
        return [_parse_comment(c) for c in raw_list]

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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _resolve_label_ids(
        self, claim_id: UUID, label_names: list[str]
    ) -> list[int]:
        """Resolve label names to Forgejo label IDs for a repo.

        Labels that do not exist are silently skipped.
        """
        repo = self._repo_path(claim_id)
        all_labels = await self._paginate_all(f"/repos/{repo}/labels")
        name_to_id = {lbl["name"]: lbl["id"] for lbl in all_labels}
        return [name_to_id[n] for n in label_names if n in name_to_id]

    async def close(self) -> None:
        """Close the underlying HTTP client.

        Should be called during application shutdown.
        """
        await self._client.aclose()
