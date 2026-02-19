# Phiacta Architecture: Git-Backed Claims

## Overview

Phiacta manages "claims" — structured assertions that are reviewed, discussed, versioned, and scored for confidence. This document describes the architecture for backing claims with git repositories, using Forgejo as the self-hosted git platform.

**Core principle:** Git for content and collaboration, Postgres for scoring and identity. Forgejo is an internal infrastructure service — users interact only through the Phiacta API.

**Immutability principle:** Nothing is deleted, everything is closed/archived. References never dangle. History is permanent.

---

## Storage Split

### Forgejo Owns (Content + Collaboration)

- Claim content files, version history
- Issues (discussion, problems, questions about a claim)
- PRs / proposals (proposed content changes with diffs)
- Branches (alternative versions, draft edits)
- Commits, file history

### Postgres Owns (Scoring + Identity + References)

- Votes (`signal + confidence + weight`, one per agent per claim)
- Reviews (structured confidence scoring)
- Confidence aggregation: `SUM(weight*confidence)/SUM(weight)` as a SQL view
- Agent identity, authentication, permissions
- The universal reference table
- Search index (denormalized claim metadata + tsvector)
- Claim metadata (denormalized from `claim.yaml` for queryability)

---

## Repo Structure

Each claim is a git repo hosted on Forgejo under a system organization.

```
forgejo.internal/phiacta/{claim_uuid}/
├── claim.md                  # claim content (or claim.tex for formal claims)
├── claim.yaml                # structured metadata
├── verification/             # all verification materials
│   ├── manifest.yaml         # declares verification type + contents
│   ├── proof.tex             # formal proofs
│   ├── data/                 # supporting datasets
│   └── scripts/              # reproducibility scripts
└── attachments/              # general supporting files (figures, etc.)
```

### claim.yaml

```yaml
format: markdown              # or: latex, structured
title: "Aspirin reduces inflammation"
claim_type: empirical
authors:
  - agent:{uuid}
tags:
  - medicine
  - pharmacology
```

### verification/manifest.yaml

```yaml
type: formal-proof            # or: empirical, computational, mixed
entries:
  - file: proof.tex
    role: primary-proof
    format: latex
  - file: scripts/reproduce.py
    role: reproducibility
    format: python
  - file: data/measurements.csv
    role: supporting-data
    format: csv
```

---

## Immutability Model

**Nothing is ever deleted.** This eliminates dangling references and preserves full history.

| Entity | Instead of deletion |
|---|---|
| Forgejo issues | Closed (with resolution label) |
| Forgejo PRs | Closed or merged, never deleted |
| Branches | Retained; merged branches prefixed with `archived/` |
| Claims | Archived/retracted status, repo made read-only |
| Votes | Withdrawn status (`deleted_at` soft delete) |
| Reviews | Withdrawn status (`deleted_at` soft delete) |
| References | Permanent — always resolve |

**Enforcement:** The Phiacta API never calls Forgejo's delete endpoints. Force-push is disabled via branch protection rules. The single Forgejo service account is the only entity with write access; users go through the API.

**Escape hatch — legal purge:** An admin-only `purge` operation for GDPR/legal requirements. Purged content is replaced with a tombstone ("content removed pursuant to [reason]") so references still resolve. Implementation: temporarily disable branch protection, use `git filter-repo` on the server to rewrite history, re-enable protection. Purge operations are logged with reason, timestamp, and admin identity.

**Branch hygiene:** When a proposal PR is merged, the source branch is renamed with an `archived/` prefix (e.g., `proposal/a1b2c3` becomes `archived/proposal/a1b2c3`). This keeps the branch listing clean while preserving history.

---

## Forgejo Configuration

### Single Service Account

Forgejo runs with one system-level service account that owns all repos. No per-user Forgejo accounts. Authentication and authorization happen entirely in the Phiacta layer.

**Git authorship:** Use the git `author` vs `committer` distinction:
- **Committer:** Always the service account (`phiacta-service <service@phiacta.local>`)
- **Author:** The actual agent (`Agent Name <{agent_uuid}@phiacta.local>`)

This preserves `git log --author=<agent>` for technical users. AI agents, organizations, and pipelines get deterministic email addresses derived from their UUID.

### Branch Protection

All repos are created with branch protection on `main`:
- No force pushes
- No branch deletion on main
- Direct commits to main allowed only via the service account (the API controls when this happens)

### Webhook Configuration

Each repo is created with a webhook pointing to `http://phiacta-api:8000/webhooks/forgejo`:
- Events: `push` (to main branch)
- Secret: HMAC shared secret for payload verification
- Content type: `application/json`

**Webhook security:** The Phiacta webhook handler verifies the HMAC-SHA256 signature on every request using the shared secret. Additionally, Forgejo should be on the same Docker network as the API, not publicly accessible.

---

## Universal Reference System

### URI Scheme

Everything in the system has an addressable URI:

```
claim:{uuid}
claim:{uuid}/issue:{number}
claim:{uuid}/pr:{number}
claim:{uuid}/commit:{sha}
claim:{uuid}/branch:{name}
interaction:{uuid}
agent:{uuid}
```

Note: Individual comments on issues/PRs are not addressable in v1. References point to the issue/PR level. This can be extended later if needed.

### PhiactaURI Type

A Pydantic-validated type that enforces the grammar:

```python
class PhiactaURI(str):
    """Validates and parses phiacta URIs.

    Grammar:
        uri            = claim_uri | interaction_uri | agent_uri
        claim_uri      = "claim:" uuid ["/" resource]
        resource       = "issue:" number
                       | "pr:" number
                       | "commit:" hex40
                       | "branch:" name
        interaction_uri = "interaction:" uuid
        agent_uri      = "agent:" uuid
        uuid           = hex8 "-" hex4 "-" hex4 "-" hex4 "-" hex12
        number         = digit+
        hex40          = 40 hex chars
        name           = [a-zA-Z0-9_/.-]+
    """

    @classmethod
    def validate(cls, v: str) -> PhiactaURI: ...

    @property
    def resource_type(self) -> str: ...
        # "claim", "issue", "pr", "commit", "branch", "interaction", "agent"

    @property
    def claim_id(self) -> UUID | None: ...
        # extracted claim UUID, or None for interaction/agent URIs
```

This module must be thorough — it is the foundation of the reference system. All URI parsing goes through this one type. No ad-hoc string splitting anywhere else.

### Reference Table

```python
class ReferenceRole(str, enum.Enum):
    EVIDENCE = "evidence"            # source cites target as supporting evidence
    REBUTS = "rebuts"                # source challenges/contradicts target
    RELATED = "related"              # general relationship, no directionality
    FIXES = "fixes"                  # source resolves the problem in target
    DERIVES_FROM = "derives_from"    # source claim is derived from target claim
    SUPERSEDES = "supersedes"        # source replaces target
    CITATION = "citation"            # source cites target as a reference
    CORROBORATION = "corroboration"  # source independently confirms target
    METHOD = "method"                # source uses target as methodology

class Reference(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "references"

    source_uri: Mapped[str] = mapped_column(nullable=False)
    target_uri: Mapped[str] = mapped_column(nullable=False)
    role: Mapped[ReferenceRole] = mapped_column(nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"), nullable=False
    )

    # Denormalized for query performance (computed on insert, immutable)
    source_type: Mapped[str] = mapped_column(nullable=False, index=True)
        # "claim", "issue", "pr", "commit", "branch", "interaction", "agent"
    target_type: Mapped[str] = mapped_column(nullable=False, index=True)
    source_claim_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    target_claim_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)

    __table_args__ = (
        Index("idx_references_source_uri", "source_uri"),
        Index("idx_references_target_uri", "target_uri"),
        Index("idx_references_source_claim", "source_claim_id"),
        Index("idx_references_target_claim", "target_claim_id"),
    )
```

The denormalized columns are derived from the URIs at insert time and never change. They enable efficient queries like:
- "All references to anything in this claim": `WHERE target_claim_id = X`
- "All issue-to-review references": `WHERE source_type = 'issue' AND target_type = 'interaction'`

### How References Are Created

**All structured references go through the Phiacta API**, regardless of direction:

```
POST /references
{
  "source": "claim:abc-def/issue:3",
  "target": "interaction:ghi-jkl",
  "role": "evidence"
}
```

Text in Forgejo issue/PR bodies is purely for human readability. The system does not parse it. No webhooks needed for reference tracking. This eliminates the asymmetry problem.

### Reference Target Validation

On creation, the API validates that the target URI resolves:
- `interaction:{uuid}` — check Postgres
- `claim:{uuid}` — check Postgres
- `claim:{uuid}/issue:{number}` — check Forgejo API
- `claim:{uuid}/pr:{number}` — check Forgejo API
- `claim:{uuid}/commit:{sha}` — check Forgejo API

If the target does not exist, the API returns 422. Since nothing is ever deleted (immutability model), validated references do not go stale under normal operation.

---

## Postgres Models

### Tables Removed

The following are replaced by this architecture:

| Old table | Replaced by |
|---|---|
| `relations` | `references` table (unified reference system) |
| `interaction_references` | `references` table |
| `interactions` rows with `kind IN ('comment', 'issue', 'suggestion')` | Forgejo issues/PRs/comments |
| `lineage_id` + `version` + `supersedes` on claims | Git commit history |

### Claim Model

```python
class Claim(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "claims"

    # Content metadata (denormalized from claim.yaml for queryability)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, default="markdown")
    # content_cache: plain text of claim.md for search, updated via webhook
    content_cache: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Organization
    namespace_id: Mapped[UUID] = mapped_column(
        ForeignKey("namespaces.id"), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"), nullable=False
    )

    # Status (note: "deprecated" in old schema renamed to "archived")
    status: Mapped[str] = mapped_column(String, default="active")
        # draft, active, archived, retracted

    # Git sync
    forgejo_repo_id: Mapped[int | None] = mapped_column(nullable=True)
    current_head_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    repo_status: Mapped[str] = mapped_column(String, default="provisioning")
        # provisioning, ready, error

    # Search
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    # Extensible metadata
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Cached confidence (refreshed on vote/review create/update/delete)
    cached_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'archived', 'retracted')",
            name="ck_claims_status",
        ),
        CheckConstraint(
            "repo_status IN ('provisioning', 'ready', 'error')",
            name="ck_claims_repo_status",
        ),
        Index("idx_claims_namespace", "namespace_id"),
        Index("idx_claims_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("idx_claims_attrs", "attrs", postgresql_using="gin"),
        Index(
            "idx_claims_active", "status",
            postgresql_where=text("status = 'active'"),
        ),
    )
```

### Interaction Model (Votes + Reviews Only)

```python
class InteractionKind(str, enum.Enum):
    VOTE = "vote"
    REVIEW = "review"

class Interaction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "interactions"

    claim_id: Mapped[UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="RESTRICT"), nullable=False
    )
    author_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)

    # Scoring
    signal: Mapped[str | None] = mapped_column(String, default=None)
        # agree, disagree, neutral
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
        # 0.0 - 1.0
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    author_trust_snapshot: Mapped[float | None] = mapped_column(Float, default=None)

    # Content (optional body text for reviews)
    body: Mapped[str | None] = mapped_column(Text, default=None)

    # Provenance
    origin_uri: Mapped[str | None] = mapped_column(Text, default=None)

    # Extensible metadata
    attrs: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    # Soft delete (withdrawn, not destroyed)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('vote', 'review')",
            name="ck_interactions_kind",
        ),
        CheckConstraint(
            "signal IS NULL OR signal IN ('agree', 'disagree', 'neutral')",
            name="ck_interactions_signal",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_interactions_confidence",
        ),
        CheckConstraint(
            "(signal IS NULL AND confidence IS NULL)"
            " OR (signal IS NOT NULL AND confidence IS NOT NULL)",
            name="ck_interactions_signal_confidence",
        ),
        CheckConstraint(
            "kind != 'vote' OR signal IS NOT NULL",
            name="ck_interactions_vote_signal",
        ),
        CheckConstraint(
            "kind != 'review' OR body IS NOT NULL",
            name="ck_interactions_body_required",
        ),
        Index("idx_interactions_claim", "claim_id"),
        Index("idx_interactions_author", "author_id"),
        Index(
            "idx_interactions_claim_signal",
            "claim_id", "signal", "confidence",
            postgresql_where=text("signal IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("idx_interactions_claim_kind", "claim_id", "kind"),
        Index(
            "uq_interactions_claim_author_signal",
            "claim_id", "author_id",
            unique=True,
            postgresql_where=text("signal IS NOT NULL AND deleted_at IS NULL"),
        ),
    )
```

### Outbox Model

Ensures Postgres-to-Forgejo consistency for write operations.

```python
class OutboxStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class OutboxOperation(str, enum.Enum):
    CREATE_REPO = "create_repo"
    COMMIT_FILES = "commit_files"
    CREATE_BRANCH = "create_branch"
    RENAME_BRANCH = "rename_branch"
    SETUP_BRANCH_PROTECTION = "setup_branch_protection"
    SETUP_WEBHOOK = "setup_webhook"

class Outbox(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "outbox"

    operation: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
        # operation-specific data (claim_id, files, branch name, etc.)
    status: Mapped[str] = mapped_column(String, default="pending")
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_outbox_status",
        ),
        Index(
            "idx_outbox_pending", "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )
```

**Outbox worker:** A background async task that:
1. Claims a pending entry atomically: `SELECT ... FROM outbox WHERE status = 'pending' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1`
2. Sets `status = 'processing'`, increments `attempts`
3. Executes the Forgejo operation via `git_service`
4. On success: sets `status = 'completed'`, records `processed_at`
5. On failure: records error in `last_error`, sets `status = 'pending'` for retry
6. After `max_attempts`: sets `status = 'failed'`, logs alert
7. Retry backoff: `min(2^attempts * 1s, 60s)`

**Compound operations:** Some operations require multiple sequential Forgejo calls (e.g., claim creation needs: create repo → commit files → setup branch protection → setup webhook). These are represented as a **single outbox entry** with `operation = 'create_repo'`. The worker handles the full sequence internally, passing intermediate results (like `repo_id`) between steps. If any step fails, the entire operation retries from the beginning (each step is idempotent). This avoids the complexity of chaining separate outbox entries.

For claim creation, the flow is:
1. API inserts Claim row with `repo_status = 'provisioning'`
2. API inserts single Outbox entry with `operation = 'create_repo'` and payload containing claim_id, files, author info
3. Worker picks it up and executes the full sequence:
   a. `git_service.create_repo(claim_id)` → gets `repo_id`
   b. `git_service.commit_files(repo_id, initial_files, ...)` → initial commit
   c. `git_service.setup_branch_protection(repo_id)`
   d. `git_service.setup_webhook(repo_id)`
4. On success: updates Claim with `repo_status = 'ready'`, `forgejo_repo_id`, `current_head_sha`
5. On failure after max retries: updates Claim to `repo_status = 'error'`

---

## Confidence View (Simplified)

Issues and suggestions no longer participate in confidence scoring. The view is purely votes and reviews.

```sql
CREATE OR REPLACE VIEW claims_with_confidence AS
SELECT
    c.id,
    c.title,
    c.claim_type,
    c.status,
    COUNT(i.id) FILTER (WHERE i.signal IS NOT NULL) AS signal_count,
    COUNT(i.id) AS interaction_count,
    SUM(i.weight * i.confidence) FILTER (WHERE i.signal = 'agree')
        / NULLIF(SUM(i.weight) FILTER (WHERE i.signal = 'agree'), 0)
        AS weighted_agree_confidence,
    COUNT(*) FILTER (WHERE i.signal = 'agree') AS agree_count,
    COUNT(*) FILTER (WHERE i.signal = 'disagree') AS disagree_count,
    COUNT(*) FILTER (WHERE i.signal = 'neutral') AS neutral_count,
    CASE
        WHEN COUNT(i.id) FILTER (WHERE i.signal IS NOT NULL) = 0 THEN 'unverified'
        WHEN COUNT(*) FILTER (WHERE i.signal = 'disagree') > 0
             AND COUNT(*) FILTER (WHERE i.signal = 'agree') > 0 THEN 'disputed'
        WHEN c.status = 'active'
             AND COUNT(*) FILTER (WHERE i.signal = 'agree') > 0
             AND SUM(i.weight * i.confidence) FILTER (WHERE i.signal = 'agree')
                 / NULLIF(SUM(i.weight) FILTER (WHERE i.signal = 'agree'), 0) > 0.7
             AND COUNT(*) FILTER (WHERE i.signal = 'agree')
                 > COUNT(*) FILTER (WHERE i.signal = 'disagree')
             THEN 'endorsed'
        -- Note: the old 'formally_verified' status was removed. Formal verification
        -- is now represented by the verification/ directory in git (with manifest.yaml).
        -- It is no longer a special epistemic status derived from a formal_content column.
        ELSE 'under_review'
    END AS epistemic_status
FROM claims c
LEFT JOIN interactions i
    ON i.claim_id = c.id
    AND i.deleted_at IS NULL
    AND i.kind IN ('vote', 'review')
GROUP BY c.id;
```

---

## `git_service.py` — Forgejo Adapter Interface

All Forgejo API calls go through this module. No Forgejo URLs, tokens, or API details leak into any other file.

```python
from dataclasses import dataclass
from uuid import UUID


@dataclass
class AgentInfo:
    """Git author identity derived from a Phiacta agent."""
    name: str
    email: str  # "{agent_uuid}@phiacta.local"


@dataclass
class CommitInfo:
    sha: str
    message: str
    author: AgentInfo
    timestamp: datetime


@dataclass
class FileContent:
    path: str
    content: str | bytes


@dataclass
class DiffInfo:
    base_sha: str
    head_sha: str
    files_changed: list[FileDiff]


@dataclass
class FileDiff:
    path: str
    patch: str  # unified diff
    additions: int
    deletions: int


@dataclass
class IssueInfo:
    number: int
    title: str
    body: str
    state: str  # "open", "closed"
    labels: list[str]
    created_by: str  # author display name
    created_at: datetime
    updated_at: datetime


@dataclass
class CommentInfo:
    id: int
    body: str
    created_by: str  # author display name
    created_at: datetime
    updated_at: datetime


@dataclass
class PullRequestInfo:
    number: int
    title: str
    body: str
    state: str  # "open", "closed", "merged" (mapped from Forgejo's state + merged flag)
    head_branch: str
    base_branch: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None


class ForgejoError(Exception):
    """Base exception for Forgejo operations."""
    pass

class RepoNotFoundError(ForgejoError):
    pass

class MergeConflictError(ForgejoError):
    """Raised when a PR cannot be merged due to conflicts."""
    conflicting_files: list[str]

class ForgejoUnavailableError(ForgejoError):
    """Raised when Forgejo is unreachable."""
    pass


class GitService(Protocol):
    """Abstract interface for git operations. All Forgejo details are internal."""

    # --- Repo lifecycle ---

    async def create_repo(self, claim_id: UUID) -> int:
        """Create a new repo for a claim. Returns Forgejo repo ID."""
        ...

    async def archive_repo(self, repo_id: int) -> None:
        """Make a repo read-only (for archived/retracted claims)."""
        ...

    async def setup_branch_protection(self, repo_id: int) -> None:
        """Configure branch protection rules on main."""
        ...

    async def setup_webhook(self, repo_id: int) -> None:
        """Register the Phiacta webhook on the repo."""
        ...

    # --- Content operations ---

    async def commit_files(
        self,
        repo_id: int,
        files: list[FileContent],
        author: AgentInfo,
        message: str,
        branch: str = "main",
    ) -> str:
        """Commit one or more files. Returns the new commit SHA."""
        ...

    async def read_file(
        self, repo_id: int, path: str, ref: str = "main"
    ) -> bytes:
        """Read a file's contents at a given ref (branch, tag, or SHA)."""
        ...

    async def list_files(
        self, repo_id: int, path: str = "", ref: str = "main"
    ) -> list[str]:
        """List file paths in a directory at a given ref."""
        ...

    # --- History ---

    async def list_commits(
        self, repo_id: int, branch: str = "main",
        limit: int = 50, page: int = 1,
    ) -> list[CommitInfo]:
        """List commits on a branch, newest first. Handles pagination."""
        ...

    async def get_diff(
        self, repo_id: int, base: str, head: str
    ) -> DiffInfo:
        """Get the diff between two refs."""
        ...

    # --- Branches ---

    async def create_branch(
        self, repo_id: int, name: str, from_ref: str = "main"
    ) -> None:
        """Create a new branch from a given ref."""
        ...

    async def rename_branch(
        self, repo_id: int, old_name: str, new_name: str
    ) -> None:
        """Rename a branch (used for archiving merged proposal branches)."""
        ...

    async def list_branches(
        self, repo_id: int, exclude_archived: bool = True
    ) -> list[str]:
        """List branches. Optionally exclude archived/* branches."""
        ...

    # --- Pull Requests (Proposals) ---

    async def create_pull_request(
        self,
        repo_id: int,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str = "main",
    ) -> PullRequestInfo:
        """Create a PR. Returns PR info including number."""
        ...

    async def merge_pull_request(
        self, repo_id: int, pr_number: int
    ) -> str:
        """Merge a PR. Returns the merge commit SHA.
        Raises MergeConflictError if not mergeable."""
        ...

    async def close_pull_request(self, repo_id: int, pr_number: int) -> None:
        """Close a PR without merging (reject proposal)."""
        ...

    async def list_pull_requests(
        self, repo_id: int, state: str = "open",
        limit: int = 50, page: int = 1,
    ) -> list[PullRequestInfo]:
        """List PRs by state."""
        ...

    async def get_pull_request(
        self, repo_id: int, pr_number: int
    ) -> PullRequestInfo:
        """Get a single PR by number."""
        ...

    # --- Issues ---

    async def create_issue(
        self, repo_id: int, title: str, body: str,
        labels: list[str] | None = None,
    ) -> IssueInfo:
        """Create an issue. Returns issue info including number."""
        ...

    async def close_issue(
        self, repo_id: int, issue_number: int
    ) -> None:
        """Close an issue."""
        ...

    async def reopen_issue(
        self, repo_id: int, issue_number: int
    ) -> None:
        """Reopen a closed issue."""
        ...

    async def list_issues(
        self, repo_id: int, state: str = "open",
        limit: int = 50, page: int = 1,
    ) -> list[IssueInfo]:
        """List issues by state."""
        ...

    async def get_issue(
        self, repo_id: int, issue_number: int
    ) -> IssueInfo:
        """Get a single issue by number."""
        ...

    # --- Comments (on issues and PRs) ---

    async def add_issue_comment(
        self, repo_id: int, issue_number: int,
        body: str, author: AgentInfo,
    ) -> CommentInfo:
        """Add a comment to an issue. Returns comment info."""
        ...

    async def list_issue_comments(
        self, repo_id: int, issue_number: int,
        limit: int = 50, page: int = 1,
    ) -> list[CommentInfo]:
        """List comments on an issue."""
        ...

    async def add_pr_comment(
        self, repo_id: int, pr_number: int,
        body: str, author: AgentInfo,
    ) -> CommentInfo:
        """Add a comment to a PR. Returns comment info."""
        ...

    async def list_pr_comments(
        self, repo_id: int, pr_number: int,
        limit: int = 50, page: int = 1,
    ) -> list[CommentInfo]:
        """List comments on a PR."""
        ...

    # --- Health ---

    async def health_check(self) -> bool:
        """Returns True if Forgejo is reachable and responsive."""
        ...
```

**Implementation details (internal to the adapter):**
- Uses `httpx.AsyncClient` with connection pooling
- Translates Forgejo HTTP errors to domain exceptions (`404 -> RepoNotFoundError`, `409 -> MergeConflictError`, `503 -> ForgejoUnavailableError`)
- Handles Forgejo API pagination transparently
- All methods are idempotent where possible (e.g., `create_repo` checks if repo already exists)
- Connection config comes from `phiacta.config` (Forgejo URL, service account token)

---

## API Design

### Backend Aggregation

The Phiacta API is the sole interface. Forgejo is never exposed to clients.

### Endpoints

```
# Claims
POST   /claims                              # Create claim (Postgres + Forgejo repo)
GET    /claims                              # List/search claims (Postgres)
GET    /claims/{id}                         # Get claim (Postgres metadata + Forgejo content)
PATCH  /claims/{id}                         # Edit claim content (commit to Forgejo)
GET    /claims/{id}/history                 # Version history (Forgejo commit log)
GET    /claims/{id}/history/{sha}           # Content at specific version
POST   /claims/{id}/attachments             # Upload file (commit to Forgejo)
GET    /claims/{id}/attachments/{name}      # Download file (Forgejo blob)

# Proposals (wraps Forgejo branches + PRs)
POST   /claims/{id}/proposals               # Create proposal (branch + PR)
GET    /claims/{id}/proposals               # List proposals
GET    /claims/{id}/proposals/{number}      # Get proposal with diff
PATCH  /claims/{id}/proposals/{number}      # Update proposal (push to branch)
POST   /claims/{id}/proposals/{number}/accept   # Merge PR
POST   /claims/{id}/proposals/{number}/reject   # Close PR

# Issues (wraps Forgejo issues)
POST   /claims/{id}/issues                  # Create issue
GET    /claims/{id}/issues                  # List issues
GET    /claims/{id}/issues/{number}         # Get issue
POST   /claims/{id}/issues/{number}/close   # Close issue
POST   /claims/{id}/issues/{number}/reopen  # Reopen issue

# Votes + Reviews (Postgres only)
POST   /claims/{id}/votes                   # Cast vote
GET    /claims/{id}/votes                   # List votes
DELETE /claims/{id}/votes/{id}              # Withdraw vote (soft delete)
POST   /claims/{id}/reviews                 # Submit review
GET    /claims/{id}/reviews                 # List reviews
DELETE /claims/{id}/reviews/{id}            # Withdraw review (soft delete)

# Confidence (Postgres only)
GET    /claims/{id}/confidence              # Aggregate confidence score

# References (Postgres only)
POST   /references                          # Create reference
GET    /references?source_claim_id=X        # List references by source
GET    /references?target_claim_id=X        # List references by target
GET    /references?target_uri=claim:X/issue:3  # List references to specific entity

# Search
GET    /claims/search?q=aspirin             # Full-text search
GET    /claims/search?q=aspirin&semantic=true  # Semantic search (future)
```

### User-Facing Vocabulary

| Git concept | User sees |
|---|---|
| Repository | Claim |
| Branch + PR | Proposal |
| Issue | Issue (same word, no git context) |
| Commit history | History / versions |
| Commit | (invisible — happens automatically) |
| Merge | Accept proposal |
| Close PR | Reject proposal |
| `git clone` | (power user only) |

### Technical User Access (Phase 6)

Power users can clone repos through an authenticated git proxy:

```
git clone https://phiacta.example.com/git/{claim_uuid}.git
```

The proxy validates Phiacta JWTs and proxies to Forgejo's internal git HTTP endpoint. This needs its own design document before implementation — it involves mapping Phiacta auth to git protocol credentials and has security implications.

---

## Consistency Model

### Write Order: Postgres First, Forgejo Async

| Operation | Postgres (synchronous) | Forgejo (via outbox) |
|---|---|---|
| Create claim | Insert row (`repo_status=provisioning`) | Create repo, initial commit, branch protection, webhook |
| Edit claim | Write to outbox | Commit files to main |
| Create proposal | Write to outbox | Create branch, commit changes, create PR |
| Create issue | Write to outbox | Create Forgejo issue |
| Cast vote | Insert interaction row | — (Postgres only) |
| Submit review | Insert interaction row | — (Postgres only) |

**If Forgejo is down:** Votes and reviews work normally. Claim creation, editing, proposals, and issues queue in the outbox and process when Forgejo recovers. The API can return `202 Accepted` for queued operations.

### Webhook Handler

Handles `push` events from Forgejo (for direct git pushes by technical users):

1. Verify HMAC-SHA256 signature
2. Look up claim by repo name (UUID)
3. Read updated `claim.yaml` from Forgejo
4. Update Postgres: `current_head_sha`, denormalized metadata, `search_tsv`
5. Re-embed content for vector search (if enabled)

---

## Key Modules

```
src/phiacta/
├── services/
│   ├── git_service.py              # Forgejo API adapter (Protocol + implementation)
│   └── outbox_worker.py            # Background worker for outbox processing
├── models/
│   ├── claim.py                    # Modified: git fields, repo_status, content_cache
│   ├── interaction.py              # Simplified: votes and reviews only
│   ├── reference.py                # New: universal reference model
│   └── outbox.py                   # New: outbox for Postgres-Forgejo consistency
├── schemas/
│   ├── uri.py                      # New: PhiactaURI Pydantic type
│   ├── claim.py                    # Modified: git-related response fields
│   ├── reference.py                # New: reference request/response schemas
│   └── interaction.py              # Simplified: votes and reviews only
├── repositories/
│   ├── claim_repository.py         # Modified: orchestrate git + Postgres
│   └── reference_repository.py     # New: reference CRUD
├── api/
│   ├── claims.py                   # Modified: proposals, issues, history, attachments
│   └── references.py               # New: reference endpoints
├── webhooks/
│   └── forgejo.py                  # New: HMAC-verified webhook handler
├── layers/
│   └── confidence/
│       └── layer.py                # Modified: simplified view (votes + reviews only)
└── config.py                       # Modified: Forgejo URL, token, webhook secret
```

**Tables removed:** `relations`, `interaction_references`
**Tables added:** `references`, `outbox`
**Tables modified:** `claims` (new columns), `interactions` (kinds reduced)

---

## Implementation Phases

### Phase 1: Foundation
1. Set up Forgejo instance (Docker Compose service, service account, `phiacta` org)
2. Implement `git_service.py` (ForgejoGitService class implementing the Protocol)
3. Implement Outbox model + worker
4. Modify Claim model (add git fields, `repo_status`, `content_cache`)
5. Alembic init + first migration (new schema from scratch — no legacy data)
6. Claim CRUD through git-backed path (create, read, edit via outbox)
7. Webhook handler (push events → update Postgres metadata)

### Phase 2: Collaboration
8. Issues via Forgejo API (create, list, close, reopen — proxied through Phiacta API)
9. Proposals via Forgejo branches + PRs (create, list, accept, reject)
10. Merge conflict detection + user-facing diff for resolution

### Phase 3: References
11. `PhiactaURI` Pydantic type with strict grammar and full test coverage
12. `Reference` model + migration
13. Reference CRUD API with target validation
14. Simplify Interaction model (drop comment/issue/suggestion kinds)
15. Update confidence view (remove `open_issue_count`, `pending_suggestion_count`)

### Phase 4: Search
16. Denormalize claim content into Postgres `tsvector` on webhook push
17. Full-text search endpoint (`GET /claims/search`)
18. `content_cache` column updated via webhook for read resilience

### Phase 5: Verification
19. `verification/manifest.yaml` schema and validation
20. Verification file upload/management API
21. Automated verification pipeline triggers (extension system)

### Phase 6: Power Users
22. Authenticated git proxy (needs its own design doc)
23. Direct git clone/push support
24. Webhook reconciliation for direct pushes

---

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Postgres-Forgejo desync | Outbox pattern with retry + webhook reconciliation |
| Repo proliferation at scale | Monitor inode/disk usage, Forgejo GC scheduling, file size limits at API |
| Forgejo downtime | Votes/reviews/search still work. Outbox queues git writes. `content_cache` serves reads. |
| Merge conflicts on proposals | API detects via Forgejo 409, returns structured diff for resolution |
| Forgejo API changes on upgrade | All calls isolated in `git_service.py`, pin Forgejo version |
| Large binary files | File size limits at API layer (50MB default), Git LFS for larger if needed later |
| Webhook forgery | HMAC-SHA256 verification + network isolation (same Docker network) |
| GDPR/legal deletion | Tombstone replacement + `git filter-repo`, logged admin-only purge operation |
| Branch proliferation | `archived/` prefix convention for merged proposal branches |
