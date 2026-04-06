# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Entry issues API.

Proxies issue operations on entry Forgejo repos.  Any authenticated
user can create an issue or comment; only the entry owner can close.

Read endpoints (list, detail) are public.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.entry_guards import (
    get_owned_entry,
    get_proposable_entry,
    get_readable_entry,
)
from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user, get_optional_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.schemas.entry_issue import (
    IssueAuthor,
    IssueCloseResponse,
    IssueCommentCreate,
    IssueCommentResponse,
    IssueCreate,
    IssueDetail,
    IssueListItem,
)
from phiacta.core.services.entity_service import EntityService
from phiacta.core.services.git_service import (
    ForgejoError,
    ForgejoUnavailableError,
    GitService,
    IssueCommentInfo,
    IssueInfo,
    RepoNotFoundError,
)
from phiacta.core.pagination import CursorPage, decode_page_cursor, encode_page_cursor
from phiacta.core.services.git_service_dep import get_git_service

logger = logging.getLogger(__name__)

_FORGEJO_MAX_LIMIT = 50

router = APIRouter(prefix="/entries", tags=["entries"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue_to_list_item(
    issue: IssueInfo, user_username: str | None = None,
) -> IssueListItem:
    return IssueListItem(
        number=issue.number,
        title=issue.title,
        body=issue.body or None,
        state=issue.state,
        author=IssueAuthor(username=user_username or issue.author_name),
        comments_count=issue.comments_count,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        closed_at=issue.closed_at,
    )


def _comment_to_response(
    comment: IssueCommentInfo, user_username: str | None = None,
) -> IssueCommentResponse:
    return IssueCommentResponse(
        id=comment.id,
        body=comment.body,
        author=IssueAuthor(username=user_username or comment.author_name),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


# ---------------------------------------------------------------------------
# Create issue
# ---------------------------------------------------------------------------


@router.post(
    "/{entry_id}/issues",
    response_model=IssueListItem,
    status_code=201,
)
@limiter.limit("30/minute")
async def create_issue(
    request: Request,
    entry_id: UUID,
    body: IssueCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> IssueListItem:
    """Create an issue on an entry's repository."""
    entry = await get_proposable_entry(entry_id, db, user=user)

    try:
        issue = await git_service.create_issue(
            entry_id,
            title=body.title,
            body=body.body or "",
            author_name=user.username,
        )
    except ForgejoUnavailableError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc
    except (RepoNotFoundError, ForgejoError) as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    # Register entity and log activity AFTER Forgejo call succeeds
    entity_service = EntityService(db)
    try:
        await entity_service.register_forgejo_entity_and_log(
            entity_type="issue",
            parent_id=entry_id,
            external_ref=f"issues/{issue.number}",
            created_by=user.id,
            action="issue.created",
            metadata={"title": issue.title},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "Entity registration failed for issue %d on entry %s (possible duplicate)",
            issue.number, entry_id,
        )

    return _issue_to_list_item(issue, user.username)


# ---------------------------------------------------------------------------
# List issues
# ---------------------------------------------------------------------------


@router.get("/{entry_id}/issues", response_model=CursorPage[IssueListItem])
async def list_issues(
    entry_id: UUID,
    state: str | None = Query(None, pattern="^(open|closed)$"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> CursorPage[IssueListItem]:
    """List issues on an entry's repository."""
    await get_readable_entry(entry_id, db, user=user)

    page = 1
    if cursor is not None:
        try:
            page = decode_page_cursor(cursor)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    effective_limit = min(limit, _FORGEJO_MAX_LIMIT)

    try:
        issues = await git_service.list_issues(
            entry_id, state=state, limit=effective_limit, page=page,
        )
    except ForgejoUnavailableError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc
    except (RepoNotFoundError, ForgejoError) as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc

    items = [_issue_to_list_item(i) for i in issues]
    has_more = len(issues) == effective_limit
    next_cursor = encode_page_cursor(page + 1) if has_more else None

    return CursorPage(items=items, limit=effective_limit, has_more=has_more, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# Get issue detail (with comments)
# ---------------------------------------------------------------------------


@router.get(
    "/{entry_id}/issues/{number}",
    response_model=IssueDetail,
)
async def get_issue_detail(
    entry_id: UUID,
    number: int,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> IssueDetail:
    """Get an issue with its comments."""
    await get_readable_entry(entry_id, db, user=user)

    try:
        issue = await git_service.get_issue(entry_id, number)
        comments = await git_service.get_issue_comments(entry_id, number)
    except ForgejoUnavailableError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc
    except (RepoNotFoundError, ForgejoError) as exc:
        raise HTTPException(
            status_code=404, detail="Issue not found",
        ) from exc

    list_item = _issue_to_list_item(issue)
    return IssueDetail(
        **list_item.model_dump(),
        comments=[_comment_to_response(c) for c in comments],
    )


# ---------------------------------------------------------------------------
# Add comment
# ---------------------------------------------------------------------------


@router.post(
    "/{entry_id}/issues/{number}/comments",
    response_model=IssueCommentResponse,
    status_code=201,
)
@limiter.limit("30/minute")
async def add_issue_comment(
    request: Request,
    entry_id: UUID,
    number: int,
    body: IssueCommentCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> IssueCommentResponse:
    """Add a comment to an issue."""
    await get_readable_entry(entry_id, db, user=user)

    try:
        comment = await git_service.create_issue_comment(
            entry_id, number, body=body.body,
        )
    except ForgejoUnavailableError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc
    except (RepoNotFoundError, ForgejoError) as exc:
        raise HTTPException(
            status_code=404, detail="Issue not found",
        ) from exc

    # Register comment entity via service
    entity_service = EntityService(db)
    try:
        await entity_service.register_comment_and_log(
            parent_id=entry_id,
            issue_external_ref=f"issues/{number}",
            created_by=user.id,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "Comment entity registration failed for issue %d on entry %s",
            number, entry_id,
        )

    return _comment_to_response(comment, user.username)


# ---------------------------------------------------------------------------
# Close issue
# ---------------------------------------------------------------------------


@router.post(
    "/{entry_id}/issues/{number}/close",
    response_model=IssueCloseResponse,
    status_code=200,
)
@limiter.limit("10/minute")
async def close_issue(
    request: Request,
    entry_id: UUID,
    number: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    git_service: GitService = Depends(get_git_service),
) -> IssueCloseResponse:
    """Close an issue. Only the entry owner can close."""
    await get_owned_entry(entry_id, user, db)

    try:
        await git_service.close_issue(entry_id, number)
    except ForgejoUnavailableError as exc:
        raise HTTPException(
            status_code=502, detail="Git service unavailable",
        ) from exc
    except (RepoNotFoundError, ForgejoError) as exc:
        raise HTTPException(
            status_code=404, detail="Issue not found",
        ) from exc

    # Log activity via service
    entity_service = EntityService(db)
    try:
        await entity_service.log_activity_for_external_ref(
            parent_id=entry_id,
            external_ref=f"issues/{number}",
            actor_id=user.id,
            action="issue.closed",
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        logger.warning(
            "Activity logging failed for closing issue %d on entry %s",
            number, entry_id,
        )

    return IssueCloseResponse(detail="Issue closed")
