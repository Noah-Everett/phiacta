# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for jobs user isolation — verifies GET /v1/jobs only returns
jobs belonging to the authenticated caller.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.jobs.models import Job  # noqa: F401 — register table
from tests.e2e.conftest import auth_header, register_user


async def insert_job(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: str,
    *,
    status: str = "pending",
    job_type: str = "test",
) -> str:
    """Insert a Job row directly and return its ID."""
    async with session_factory() as session:
        job = Job(
            id=uuid4(),
            job_type=job_type,
            submitted_by=UUID(user_id),
            entity_id=None,
            input={},
            status=status,
        )
        session.add(job)
        await session.commit()
        return str(job.id)


class TestJobsUserIsolation:
    async def test_user_only_sees_own_jobs(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Two users with different jobs — each sees only their own."""
        alice = await register_user(client, username=f"alice-{uuid4().hex[:8]}")
        bob = await register_user(client, username=f"bob-{uuid4().hex[:8]}")

        alice_job = await insert_job(e2e_session_factory, alice["user"]["id"])
        bob_job = await insert_job(e2e_session_factory, bob["user"]["id"])

        # Alice sees only her job
        resp = await client.get(
            "/v1/jobs?status=pending",
            headers=auth_header(alice["access_token"]),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        job_ids = {j["id"] for j in items}
        assert alice_job in job_ids
        assert bob_job not in job_ids

        # Bob sees only his job
        resp = await client.get(
            "/v1/jobs?status=pending",
            headers=auth_header(bob["access_token"]),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        job_ids = {j["id"] for j in items}
        assert bob_job in job_ids
        assert alice_job not in job_ids

    async def test_user_with_no_jobs_sees_empty_list(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        user = await register_user(client, username=f"empty-{uuid4().hex[:8]}")
        resp = await client.get(
            "/v1/jobs?status=pending,running,completed,failed",
            headers=auth_header(user["access_token"]),
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_unauthenticated_returns_empty_list(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        resp = await client.get("/v1/jobs")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_status_filter(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Status filter correctly restricts results."""
        user = await register_user(client, username=f"filter-{uuid4().hex[:8]}")
        uid = user["user"]["id"]

        pending_job = await insert_job(e2e_session_factory, uid, status="pending")
        completed_job = await insert_job(e2e_session_factory, uid, status="completed")

        # Filter by completed only
        resp = await client.get(
            "/v1/jobs?status=completed",
            headers=auth_header(user["access_token"]),
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1, f"Expected exactly 1 completed job, got {len(items)}"
        job_ids = {j["id"] for j in items}
        assert completed_job in job_ids
        assert pending_job not in job_ids

    async def test_invalid_status_returns_400(
        self,
        client: httpx.AsyncClient,
    ) -> None:
        """Requesting an invalid status value returns 400."""
        user = await register_user(client, username=f"badstatus-{uuid4().hex[:8]}")
        resp = await client.get(
            "/v1/jobs?status=bogus",
            headers=auth_header(user["access_token"]),
        )
        assert resp.status_code == 400
        assert "Invalid status" in resp.json()["detail"]
