# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Jobs API — GET /v1/jobs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.api.rate_limit import limiter
from phiacta.core.auth.dependencies import get_current_user
from phiacta.core.db.session import get_db
from phiacta.core.models.user import User
from phiacta.core.pagination import CursorPage, build_keyset_cursor, decode_keyset_cursor
from phiacta.core.schemas.job import JobResponse
from phiacta.jobs.repository import JobRepository

router = APIRouter(prefix="/jobs", tags=["jobs"])

_VALID_STATUSES = {"pending", "running", "completed", "failed"}
_DEFAULT_STATUSES = ["pending", "running"]


@router.get("", response_model=CursorPage[JobResponse])
@limiter.limit("300/minute")
async def list_jobs(
    request: Request,
    status: str | None = Query(
        None,
        description="Comma-separated statuses to include. Defaults to pending,running.",
    ),
    job_type: str | None = Query(None),
    entity_id: UUID | None = Query(None, description="Filter by entity ID."),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CursorPage[JobResponse]:
    """List jobs submitted by the calling user. Requires authentication.

    ``status`` accepts a comma-separated list, e.g. ``pending,running``.
    Defaults to ``pending,running`` when omitted.
    """
    if status is not None:
        requested = [s.strip() for s in status.split(",") if s.strip()]
        invalid = set(requested) - _VALID_STATUSES
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status value(s): {', '.join(sorted(invalid))}",
            )
        status_filter: list[str] | None = requested or None
    else:
        status_filter = _DEFAULT_STATUSES

    cursor_created_at: str | None = None
    cursor_job_id: UUID | None = None
    if cursor is not None:
        try:
            cursor_created_at, cursor_job_id = decode_keyset_cursor(cursor, "created_at", "desc")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo = JobRepository(db)
    jobs = await repo.list_jobs(
        limit=limit + 1,
        submitted_by=user.id,
        status=status_filter,
        job_type=job_type,
        entity_id=entity_id,
        cursor_created_at=cursor_created_at,
        cursor_id=cursor_job_id,
    )

    has_more = len(jobs) > limit
    if has_more:
        jobs = jobs[:limit]

    next_cursor = None
    if has_more and jobs:
        last = jobs[-1]
        next_cursor = build_keyset_cursor("created_at", "desc", last.created_at, last.id)

    return CursorPage(
        items=[JobResponse.model_validate(j) for j in jobs],
        limit=limit,
        has_more=has_more,
        next_cursor=next_cursor,
    )


@router.get("/{job_id}", response_model=JobResponse)
@limiter.limit("300/minute")
async def get_job(
    request: Request,
    job_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """Get a single job by ID. Only returns jobs submitted by the caller."""
    repo = JobRepository(db)
    job = await repo.get(job_id)
    if job is None or job.submitted_by != user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.model_validate(job)
