# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for the cross-process submit_and_wait (DB-polling approach)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4

import pytest

from phiacta.jobs.submit import submit_and_wait


# --- Helpers ----------------------------------------------------------------


def _make_job(*, status: str = "pending", job_id=None):
    job = MagicMock()
    job.id = job_id or uuid4()
    job.status = status
    job.result = {"ok": True} if status == "completed" else None
    job.last_error = "boom" if status == "failed" else None
    return job


def _patch_submit(mock_repo):
    """Context manager that patches session factory and JobRepository."""
    mock_session = AsyncMock()
    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    return (
        patch(
            "phiacta.jobs.submit.async_sessionmaker",
            return_value=MagicMock(return_value=mock_session_ctx),
        ),
        patch(
            "phiacta.jobs.submit.JobRepository",
            return_value=mock_repo,
        ),
        mock_session,
    )


# --- Tests ------------------------------------------------------------------


class TestSubmitAndWait:
    async def test_returns_completed_job(self) -> None:
        """Polls DB until job reaches completed status."""
        pending_job = _make_job(status="pending")
        completed_job = _make_job(status="completed", job_id=pending_job.id)

        mock_repo = AsyncMock()
        mock_repo.create.return_value = pending_job
        mock_repo.get.side_effect = [pending_job, completed_job]

        p1, p2, mock_session = _patch_submit(mock_repo)
        with p1, p2:
            result = await submit_and_wait(
                AsyncMock(),
                job_type="test",
                input={"x": 1},
                submitted_by=uuid4(),
                poll_interval=0.01,
            )

        assert result.status == "completed"
        assert result.result == {"ok": True}

    async def test_returns_failed_job(self) -> None:
        """Polls DB and returns failed job — no submitter-side retry."""
        pending_job = _make_job(status="pending")
        failed_job = _make_job(status="failed", job_id=pending_job.id)

        mock_repo = AsyncMock()
        mock_repo.create.return_value = pending_job
        mock_repo.get.side_effect = [pending_job, failed_job]

        p1, p2, _ = _patch_submit(mock_repo)
        with p1, p2:
            result = await submit_and_wait(
                AsyncMock(),
                job_type="test",
                input={},
                submitted_by=uuid4(),
                poll_interval=0.01,
            )

        assert result.status == "failed"

    async def test_multi_poll_transition(self) -> None:
        """Realistic path: pending → running → running → completed."""
        job_id = uuid4()
        pending = _make_job(status="pending", job_id=job_id)
        running1 = _make_job(status="running", job_id=job_id)
        running2 = _make_job(status="running", job_id=job_id)
        completed = _make_job(status="completed", job_id=job_id)

        mock_repo = AsyncMock()
        mock_repo.create.return_value = pending
        mock_repo.get.side_effect = [pending, running1, running2, completed]

        p1, p2, _ = _patch_submit(mock_repo)
        with p1, p2:
            result = await submit_and_wait(
                AsyncMock(),
                job_type="test",
                input={},
                submitted_by=uuid4(),
                poll_interval=0.01,
            )

        assert result.status == "completed"
        assert mock_repo.get.call_count == 4

    async def test_timeout_returns_current_state(self) -> None:
        """When poll times out, returns the job in whatever state it's in."""
        job_id = uuid4()
        running_job = _make_job(status="running", job_id=job_id)

        mock_repo = AsyncMock()
        mock_repo.create.return_value = running_job
        # Always returns running — never reaches terminal state
        mock_repo.get.return_value = running_job

        p1, p2, _ = _patch_submit(mock_repo)
        with p1, p2:
            result = await submit_and_wait(
                AsyncMock(),
                job_type="test",
                input={},
                submitted_by=uuid4(),
                timeout_seconds=0,  # immediate timeout
                poll_interval=0.01,
            )

        assert result.status == "running"

    async def test_raises_if_job_disappears_during_poll(self) -> None:
        """Raises RuntimeError if the job row vanishes mid-poll."""
        pending_job = _make_job(status="pending")

        mock_repo = AsyncMock()
        mock_repo.create.return_value = pending_job
        mock_repo.get.return_value = None

        p1, p2, _ = _patch_submit(mock_repo)
        with p1, p2:
            with pytest.raises(RuntimeError, match="disappeared"):
                await submit_and_wait(
                    AsyncMock(),
                    job_type="test",
                    input={},
                    submitted_by=uuid4(),
                    poll_interval=0.01,
                )

    async def test_raises_if_job_disappears_after_timeout(self) -> None:
        """Raises RuntimeError if job vanishes during the final post-timeout fetch."""
        job_id = uuid4()
        running_job = _make_job(status="running", job_id=job_id)

        mock_repo = AsyncMock()
        mock_repo.create.return_value = running_job
        # During poll: running. After timeout final fetch: gone.
        mock_repo.get.side_effect = [running_job, None]

        p1, p2, _ = _patch_submit(mock_repo)
        with p1, p2:
            with pytest.raises(RuntimeError, match="disappeared"):
                await submit_and_wait(
                    AsyncMock(),
                    job_type="test",
                    input={},
                    submitted_by=uuid4(),
                    timeout_seconds=0,
                    poll_interval=0.01,
                )

    async def test_creates_job_with_correct_params(self) -> None:
        """Verifies job is created with the exact parameters passed in."""
        job = _make_job(status="completed")
        user_id = uuid4()
        entry_id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.create.return_value = job
        mock_repo.get.return_value = job

        p1, p2, _ = _patch_submit(mock_repo)
        with p1, p2:
            await submit_and_wait(
                AsyncMock(),
                job_type="compiled_content",
                input={"entry_id": "abc"},
                submitted_by=user_id,
                entry_id=entry_id,
                timeout_seconds=60,
                poll_interval=0.01,
            )

        mock_repo.create.assert_called_once_with(
            job_type="compiled_content",
            submitted_by=user_id,
            input={"entry_id": "abc"},
            entry_id=entry_id,
            timeout_seconds=60,
        )

    async def test_commits_after_create(self) -> None:
        """Verifies session.commit() is called after job creation."""
        job = _make_job(status="completed")

        mock_repo = AsyncMock()
        mock_repo.create.return_value = job
        mock_repo.get.return_value = job

        p1, p2, mock_session = _patch_submit(mock_repo)
        with p1, p2:
            await submit_and_wait(
                AsyncMock(),
                job_type="test",
                input={},
                submitted_by=uuid4(),
                poll_interval=0.01,
            )

        mock_session.commit.assert_called()

    async def test_entry_id_defaults_to_none(self) -> None:
        """entry_id is optional and defaults to None."""
        job = _make_job(status="completed")

        mock_repo = AsyncMock()
        mock_repo.create.return_value = job
        mock_repo.get.return_value = job

        user_id = uuid4()
        p1, p2, _ = _patch_submit(mock_repo)
        with p1, p2:
            await submit_and_wait(
                AsyncMock(),
                job_type="test",
                input={},
                submitted_by=user_id,
                poll_interval=0.01,
            )

        mock_repo.create.assert_called_once_with(
            job_type="test",
            submitted_by=user_id,
            input={},
            entry_id=None,
            timeout_seconds=120,
        )
