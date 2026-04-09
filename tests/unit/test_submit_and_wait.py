# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for the cross-process submit_and_wait (DB-polling approach)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from phiacta.jobs.submit import submit_and_wait


def _make_job(*, status: str = "pending", job_id=None):
    job = MagicMock()
    job.id = job_id or uuid4()
    job.status = status
    job.result = {"ok": True} if status == "completed" else None
    job.last_error = "boom" if status == "failed" else None
    return job


class TestSubmitAndWait:
    async def test_returns_completed_job(self) -> None:
        """Polls DB until job reaches terminal state."""
        engine = AsyncMock()
        pending_job = _make_job(status="pending")
        completed_job = _make_job(status="completed", job_id=pending_job.id)

        mock_repo = AsyncMock()
        mock_repo.create.return_value = pending_job
        # First poll: still pending. Second poll: completed.
        mock_repo.get.side_effect = [pending_job, completed_job]

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "phiacta.jobs.submit.async_sessionmaker",
            return_value=MagicMock(return_value=mock_session_ctx),
        ), patch(
            "phiacta.jobs.submit.JobRepository",
            return_value=mock_repo,
        ):
            result = await submit_and_wait(
                engine,
                job_type="test",
                input={"x": 1},
                submitted_by=uuid4(),
                poll_interval=0.01,
            )

        assert result.status == "completed"

    async def test_returns_failed_job(self) -> None:
        """Polls DB and returns failed job without retrying from submitter side."""
        engine = AsyncMock()
        pending_job = _make_job(status="pending")
        failed_job = _make_job(status="failed", job_id=pending_job.id)

        mock_repo = AsyncMock()
        mock_repo.create.return_value = pending_job
        mock_repo.get.side_effect = [pending_job, failed_job]

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "phiacta.jobs.submit.async_sessionmaker",
            return_value=MagicMock(return_value=mock_session_ctx),
        ), patch(
            "phiacta.jobs.submit.JobRepository",
            return_value=mock_repo,
        ):
            result = await submit_and_wait(
                engine,
                job_type="test",
                input={},
                submitted_by=uuid4(),
                poll_interval=0.01,
            )

        assert result.status == "failed"

    async def test_raises_if_job_disappears(self) -> None:
        """Raises RuntimeError if the job row vanishes mid-poll."""
        engine = AsyncMock()
        pending_job = _make_job(status="pending")

        mock_repo = AsyncMock()
        mock_repo.create.return_value = pending_job
        mock_repo.get.return_value = None  # job disappeared

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "phiacta.jobs.submit.async_sessionmaker",
            return_value=MagicMock(return_value=mock_session_ctx),
        ), patch(
            "phiacta.jobs.submit.JobRepository",
            return_value=mock_repo,
        ):
            with pytest.raises(RuntimeError, match="disappeared"):
                await submit_and_wait(
                    engine,
                    job_type="test",
                    input={},
                    submitted_by=uuid4(),
                    poll_interval=0.01,
                )

    async def test_creates_job_with_correct_params(self) -> None:
        """Verifies the job is created with the right parameters."""
        engine = AsyncMock()
        job = _make_job(status="completed")
        user_id = uuid4()
        entry_id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.create.return_value = job
        mock_repo.get.return_value = job

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "phiacta.jobs.submit.async_sessionmaker",
            return_value=MagicMock(return_value=mock_session_ctx),
        ), patch(
            "phiacta.jobs.submit.JobRepository",
            return_value=mock_repo,
        ):
            await submit_and_wait(
                engine,
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
