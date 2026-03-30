# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry edit proposals API (NEV-126, NEV-162).

Proxies pull request operations on entry Forgejo repos.  Any authenticated
user can create a proposal; only the entry owner can merge or close.

Read endpoints (list, detail) are public.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.entry_files import validate_file_path
from phiacta.core.api.entry_guards import (
    get_owned_entry,
    get_proposable_entry,
    get_readable_entry,
    get_writable_entry,
)
from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user, get_optional_user
from phiacta.config import Settings, get_settings
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.schemas.entry_edit import (
    EditProposalCloseResponse,
    EditProposalCreate,
    EditProposalDetail,
    EditProposalFileDiff,
    EditProposalListItem,
    EditProposalMergeResponse,
)
from phiacta.core.services.entity_service import EntityService
from phiacta.core.services.git_service import (
    AuthorInfo,
    FileContent,
    ForgejoError,
    ForgejoUnavailableError,
    GitService,
    PullRequestInfo,
    RepoNotFoundError,
)
from phiacta.core.services.git_service_dep import get_git_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entries", tags=["entries"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, max_length: int = 60) -> str:
    """Convert text to a URL/branch-safe slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().strip()
    text = _SLUG_RE.sub("-", text).strip("-")
    return text[:max_length] or "proposal"


def _make_branch_name(username: str, title: str) -> str:
    """Generate a branch name for a proposal: ``edit/{username}/{slug}``."""
    return f"edit/{username}/{_slugify(title)}"


def _pr_to_list_item(
    pr: PullRequestInfo,
    user_username: str | None = None,
) -> EditProposalListItem:
    return EditProposalListItem(
        number=pr.number,
        title=pr.title,
        body=pr.body,
        state=pr.state,
        is_draft=pr.is_draft,
        author={
            "username": user_username or pr.author_name,
        },
        head_branch=pr.head_branch,
        base_branch=pr.base_branch,
        created_at=pr.created_at,
        updated_at=pr.updated_at,
        merged_at=pr.merged_at,
    )


# ---------------------------------------------------------------------------
# Create edit proposal
# ---------------------------------------------------------------------------


@router.post(
    "/{entry_id}/edits",
    response_model=EditProposalListItem,
    status_code=201,
)
@limiter.limit("30/minute")
async def create_edit_proposal(
    request: Request,
    entry_id: UUID,
    body: EditProposalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
    settings: Settings = Depends(get_settings),
) -> EditProposalListItem:
    """Create an edit proposal (branch + PR) for an entry."""
    entry = await get_proposable_entry(entry_id, db, user=user)

    # Validate all file paths before touching Forgejo.
    for fc in body.files:
        try:
            validate_file_path(fc.path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid file path") from exc

    # Validate file sizes (content is plain text, not base64).
    validated_files: list[FileContent] = []
    for fc in body.files:
        raw_size = len(fc.content.encode("utf-8"))
        if raw_size > settings.max_file_size_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File content exceeds maximum size of {settings.max_file_size_bytes} bytes",
            )
        validated_files.append(FileContent(path=fc.path, content=fc.content))

    # Step 1: Create branch from main.
    branch_name = _make_branch_name(user.username, body.title)
    try:
        await git_service.create_branch(entry_id, branch_name)
    except ForgejoUnavailableError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc
    except ForgejoError:
        # Branch name collision — append a suffix and retry once.
        branch_name = f"{branch_name}-2"
        try:
            await git_service.create_branch(entry_id, branch_name)
        except ForgejoError as exc:
            raise HTTPException(
                status_code=502, detail="Git service unavailable",
            ) from exc

    # Step 2: Commit files to the proposal branch.
    author = AuthorInfo(name=user.username, email=f"{user.id}@phiacta.local")
    message = body.title
    try:
        await git_service.commit_files(
            entry_id, validated_files, author, message, branch=branch_name,
        )
    except (RepoNotFoundError, ForgejoError) as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    # Step 3: Create pull request.
    pr_body = body.body or ""
    try:
        pr_info = await git_service.create_pull_request(
            entry_id,
            title=body.title,
            body=pr_body,
            head_branch=branch_name,
            base_branch="main",
            author_name=user.username,
        )
    except (RepoNotFoundError, ForgejoError) as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    # Register entity and log activity AFTER Forgejo call succeeds
    entity_service = EntityService(db)
    try:
        await entity_service.register_forgejo_entity_and_log(
            entity_type="edit",
            parent_id=entry_id,
            external_ref=f"pulls/{pr_info.number}",
            created_by=user.id,
            action="edit.created",
            metadata={"title": pr_info.title},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "Entity registration failed for edit PR %d on entry %s",
            pr_info.number, entry_id,
        )

    return _pr_to_list_item(pr_info, user.username)


# ---------------------------------------------------------------------------
# List edit proposals
# ---------------------------------------------------------------------------


@router.get("/{entry_id}/edits", response_model=list[EditProposalListItem])
async def list_edit_proposals(
    entry_id: UUID,
    state: str | None = Query(None, pattern="^(open|closed|merged)$"),
    limit: int = Query(50, ge=1, le=200),
    page: int = Query(1, ge=1),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> list[EditProposalListItem]:
    """List edit proposals for an entry, optionally filtered by state."""
    await get_readable_entry(entry_id, db, user=user)

    try:
        prs = await git_service.list_pull_requests(
            entry_id, state=state, limit=limit, page=page,
        )
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Entry repository not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    return [_pr_to_list_item(pr) for pr in prs]


# ---------------------------------------------------------------------------
# Get proposal detail
# ---------------------------------------------------------------------------


@router.get(
    "/{entry_id}/edits/{number}",
    response_model=EditProposalDetail,
)
async def get_edit_proposal_detail(
    entry_id: UUID,
    number: int,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> EditProposalDetail:
    """Get full detail for a single edit proposal, including the diff."""
    await get_readable_entry(entry_id, db, user=user)

    try:
        pr = await git_service.get_pull_request(entry_id, number)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Edit proposal not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    try:
        diff_info = await git_service.get_pull_request_diff(entry_id, number)
    except (RepoNotFoundError, ForgejoError):
        diff_info = None

    diff_files: list[EditProposalFileDiff] = []
    if diff_info:
        for fd in diff_info.files_changed:
            diff_files.append(EditProposalFileDiff(
                path=fd.path,
                patch=fd.patch,
                additions=fd.additions,
                deletions=fd.deletions,
            ))

    base = _pr_to_list_item(pr)
    return EditProposalDetail(**base.model_dump(), diff=diff_files)


# ---------------------------------------------------------------------------
# Merge proposal
# ---------------------------------------------------------------------------


@router.post(
    "/{entry_id}/edits/{number}/merge",
    response_model=EditProposalMergeResponse,
)
@limiter.limit("10/minute")
async def merge_edit_proposal(
    request: Request,
    entry_id: UUID,
    number: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> EditProposalMergeResponse:
    """Merge an edit proposal. Only the entry owner can merge."""
    await get_writable_entry(entry_id, user, db)

    # Verify the PR exists and is open.
    try:
        pr = await git_service.get_pull_request(entry_id, number)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Edit proposal not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    if pr.state == "merged":
        raise HTTPException(
            status_code=409, detail="Edit proposal is already merged",
        )
    if pr.state == "closed":
        raise HTTPException(
            status_code=409, detail="Edit proposal is closed",
        )

    # Pre-merge validation: check diff for .phiacta/ files.
    try:
        diff_info = await git_service.get_pull_request_diff(entry_id, number)
        for fd in diff_info.files_changed:
            try:
                validate_file_path(fd.path)
            except ValueError as exc:
                logger.warning(
                    "Merge blocked: PR #%d on entry %s contains .phiacta/ changes",
                    number, entry_id,
                )
                raise HTTPException(
                    status_code=422,
                    detail="Proposal contains changes to .phiacta/ which is not allowed",
                ) from exc
    except HTTPException:
        raise
    except (RepoNotFoundError, ForgejoError):
        pass  # If we can't get the diff, proceed — Forgejo will catch conflicts.

    # Merge.
    try:
        sha = await git_service.merge_pull_request(entry_id, number)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail="Pull request cannot be merged",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    # Log activity via service
    entity_service = EntityService(db)
    try:
        await entity_service.log_activity_for_external_ref(
            parent_id=entry_id,
            external_ref=f"pulls/{number}",
            actor_id=user.id,
            action="edit.merged",
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "Activity logging failed for merging edit PR %d on entry %s",
            number, entry_id,
        )

    return EditProposalMergeResponse(sha=sha)


# ---------------------------------------------------------------------------
# Close proposal
# ---------------------------------------------------------------------------


@router.post(
    "/{entry_id}/edits/{number}/close",
    response_model=EditProposalCloseResponse,
    status_code=200,
)
@limiter.limit("10/minute")
async def close_edit_proposal(
    request: Request,
    entry_id: UUID,
    number: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> EditProposalCloseResponse:
    """Close/reject an edit proposal. Only the entry owner can close."""
    entry = await get_owned_entry(entry_id, user, db)

    if entry.repo_status != "ready":
        raise HTTPException(
            status_code=409, detail="Entry repository is not yet ready",
        )

    try:
        await git_service.close_pull_request(entry_id, number)
    except RepoNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Edit proposal not found",
        ) from exc
    except ForgejoError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    # Log activity via service
    entity_service = EntityService(db)
    try:
        await entity_service.log_activity_for_external_ref(
            parent_id=entry_id,
            external_ref=f"pulls/{number}",
            actor_id=user.id,
            action="edit.closed",
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "Activity logging failed for closing edit PR %d on entry %s",
            number, entry_id,
        )

    return EditProposalCloseResponse(detail="Edit proposal closed")
