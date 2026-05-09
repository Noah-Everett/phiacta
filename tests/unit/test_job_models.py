# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for Job model behavior and SecurityPolicy constraints."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.core.models.user import User
from phiacta.jobs.models import Job
from phiacta.jobs.security import SecurityPolicy
from tests.conftest import make_user


async def _seed_user(db: AsyncSession) -> User:
    user = User(**make_user())
    db.add(user)
    await db.flush()
    return user


class TestJobDefaults:
    """A newly created job should start in a safe, pending state."""

    async def test_new_job_starts_pending(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        job = Job(job_type="latex", submitted_by=user.id, input={"source": "main.tex"})
        db_session.add(job)
        await db_session.flush()

        assert job.status == "pending"

    async def test_new_job_has_zero_attempts(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        job = Job(job_type="latex", submitted_by=user.id, input={})
        db_session.add(job)
        await db_session.flush()

        assert job.attempts == 0

    async def test_new_job_default_timeout_is_120s(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        job = Job(job_type="latex", submitted_by=user.id, input={})
        db_session.add(job)
        await db_session.flush()

        assert job.timeout_seconds == 120

    async def test_new_job_allows_3_attempts_by_default(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        job = Job(job_type="latex", submitted_by=user.id, input={})
        db_session.add(job)
        await db_session.flush()

        assert job.max_attempts == 3

    async def test_new_job_has_no_result_or_timestamps(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        job = Job(job_type="latex", submitted_by=user.id, input={})
        db_session.add(job)
        await db_session.flush()

        assert job.result is None
        assert job.last_error is None
        assert job.container_id is None
        assert job.claimed_at is None
        assert job.started_at is None
        assert job.completed_at is None


class TestJobInputOutput:
    """Jobs store structured input/output as JSON dicts."""

    async def test_input_roundtrips_as_dict(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        payload = {"entry_id": str(uuid4()), "format": "pdf"}
        job = Job(job_type="latex", submitted_by=user.id, input=payload)
        db_session.add(job)
        await db_session.flush()

        fetched = await db_session.get(Job, job.id)
        assert fetched.input == payload

    async def test_result_roundtrips_as_dict(self, db_session: AsyncSession) -> None:
        user = await _seed_user(db_session)
        job = Job(job_type="latex", submitted_by=user.id, input={})
        db_session.add(job)
        await db_session.flush()

        job.result = {"exit_code": 0, "log": "Success"}
        await db_session.flush()

        fetched = await db_session.get(Job, job.id)
        assert fetched.result["exit_code"] == 0


class TestSecurityPolicy:
    """SecurityPolicy should be restrictive by default and immutable."""

    def test_defaults_are_restrictive(self) -> None:
        sp = SecurityPolicy()
        assert sp.network_disabled is True
        assert sp.read_only_rootfs is True
        assert sp.cap_drop == ("ALL",)
        assert sp.memory_mb == 512
        assert sp.max_pids == 64

    def test_immutable(self) -> None:
        sp = SecurityPolicy()
        with pytest.raises(AttributeError):
            sp.memory_mb = 9999  # type: ignore[misc]

    def test_custom_overrides(self) -> None:
        sp = SecurityPolicy(memory_mb=2048, timeout_seconds=300, network_disabled=False)
        assert sp.memory_mb == 2048
        assert sp.timeout_seconds == 300
        assert sp.network_disabled is False
        # Other defaults still hold
        assert sp.read_only_rootfs is True
        assert sp.cap_drop == ("ALL",)
