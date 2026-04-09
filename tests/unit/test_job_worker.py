# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for JobWorker — poll loop, dispatch, coordination, and error handling.

Uses mocked session factories and handlers to test worker logic in isolation.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from phiacta.jobs.worker import JobWorker, _backoff_seconds
from phiacta.tools.base import JobContext, JobHandler, JobInfraError


# --- Helpers ----------------------------------------------------------------


class _SuccessHandler(JobHandler):
    """Handler that always succeeds."""

    async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return {"status": "ok", **input}


class _FailHandler(JobHandler):
    """Handler that always raises a permanent error."""

    async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        raise ValueError("bad input")


class _InfraFailHandler(JobHandler):
    """Handler that always raises an infrastructure error."""

    async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        raise JobInfraError("docker daemon unreachable")


class _SlowHandler(JobHandler):
    """Handler that takes longer than the job timeout."""

    async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        await asyncio.sleep(999)
        return {}


# --- Backoff ----------------------------------------------------------------


class TestBackoff:
    def test_first_attempt(self) -> None:
        assert _backoff_seconds(0) == 5.0

    def test_exponential_growth(self) -> None:
        assert _backoff_seconds(1) == 10.0
        assert _backoff_seconds(2) == 20.0
        assert _backoff_seconds(3) == 40.0

    def test_capped_at_5_minutes(self) -> None:
        assert _backoff_seconds(10) == 300.0
        assert _backoff_seconds(100) == 300.0


# --- submit_and_wait --------------------------------------------------------


class TestSubmitAndWait:
    async def test_rejects_unknown_job_type(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={"latex": _SuccessHandler()})

        with pytest.raises(ValueError, match="Unknown job type"):
            await worker.submit_and_wait(
                job_type="nonexistent",
                input={},
                submitted_by=uuid4(),
            )

    async def test_registers_and_cleans_up_waiter(self) -> None:
        """Verify waiter is registered during submit and cleaned up after."""
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={"test": _SuccessHandler()})

        # Mock session factory to return a mock session
        mock_session = AsyncMock()
        mock_job = MagicMock()
        mock_job.id = uuid4()
        mock_job.status = "completed"
        mock_job.result = {"ok": True}

        mock_repo = AsyncMock()
        mock_repo.create.return_value = mock_job
        mock_repo.get.return_value = mock_job

        # Patch JobRepository to return our mock
        with patch("phiacta.jobs.worker.JobRepository", return_value=mock_repo):
            # Make the session factory context manager work
            mock_session_ctx = AsyncMock()
            mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
            worker._session_factory = MagicMock(return_value=mock_session_ctx)

            # Set up a task that fires the event after a short delay
            async def _fire_event():
                await asyncio.sleep(0.05)
                event = worker._waiters.get(mock_job.id)
                if event:
                    event.set()

            task = asyncio.create_task(_fire_event())

            result = await worker.submit_and_wait(
                job_type="test",
                input={"x": 1},
                submitted_by=uuid4(),
                timeout_seconds=5,
            )

            await task
            assert result is mock_job
            # Waiter should be cleaned up
            assert mock_job.id not in worker._waiters


# --- _notify ----------------------------------------------------------------


class TestNotify:
    def test_sets_event_for_registered_waiter(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        job_id = uuid4()
        event = asyncio.Event()
        worker._waiters[job_id] = event

        worker._notify(job_id)
        assert event.is_set()

    def test_noop_for_unregistered_job(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        # Should not raise
        worker._notify(uuid4())


# --- Handler dispatch -------------------------------------------------------


class TestHandlerLookup:
    def test_handlers_stored(self) -> None:
        handler = _SuccessHandler()
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={"latex": handler})
        assert worker._handlers["latex"] is handler

    def test_empty_handlers(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        assert len(worker._handlers) == 0
