# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for JobWorker — poll loop, dispatch, and error handling.

Uses mocked session factories and handlers to test worker logic in isolation.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from phiacta.jobs.worker import JobWorker, _backoff_seconds
from phiacta.tools.base import JobContext, JobHandler, JobInfraError


# --- Helpers ----------------------------------------------------------------


def _make_job(
    *,
    job_type: str = "test",
    timeout_seconds: float = 120,
    attempts: int = 0,
    max_attempts: int = 3,
) -> MagicMock:
    """Create a mock Job with the attributes _process_job reads."""
    job = MagicMock()
    job.id = uuid4()
    job.job_type = job_type
    job.input = {"key": "value"}
    job.submitted_by = uuid4()
    job.timeout_seconds = timeout_seconds
    job.attempts = attempts
    job.max_attempts = max_attempts
    return job


def _mock_session_factory() -> AsyncMock:
    """Return a mock async_sessionmaker that yields a mock session."""
    session = AsyncMock()
    session.commit = AsyncMock()

    @asynccontextmanager
    async def _factory():
        yield session

    factory = MagicMock(side_effect=_factory)
    return factory, session


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


# --- _process_job -----------------------------------------------------------


class TestProcessJob:
    """Test _process_job dispatch, failure paths, and retry logic."""

    async def test_unknown_handler_marks_failed(self) -> None:
        """Job with unregistered job_type is immediately failed."""
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={"latex": _SuccessHandler()})
        factory, session = _mock_session_factory()
        worker._session_factory = factory

        mock_repo = AsyncMock()
        job = _make_job(job_type="unknown_type")

        with patch("phiacta.jobs.worker.JobRepository", return_value=mock_repo):
            await worker._process_job(job)

        mock_repo.mark_failed.assert_awaited_once()
        call_args = mock_repo.mark_failed.call_args
        assert "No handler" in call_args[0][1]

    async def test_timeout_triggers_retry(self) -> None:
        """Handler that exceeds timeout triggers _handle_retry."""
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={"slow": _SlowHandler()})
        factory, session = _mock_session_factory()
        worker._session_factory = factory

        job = _make_job(job_type="slow", timeout_seconds=0.01)

        with patch.object(worker, "_handle_retry", new_callable=AsyncMock) as mock_retry:
            await worker._process_job(job)

        mock_retry.assert_awaited_once()
        assert job is mock_retry.call_args[0][0]
        assert "timed out" in mock_retry.call_args[0][1]

    async def test_permanent_failure_marks_failed_no_retry(self) -> None:
        """Non-JobInfraError exception marks job as failed without retry."""
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={"fail": _FailHandler()})
        factory, session = _mock_session_factory()
        worker._session_factory = factory

        mock_repo = AsyncMock()
        job = _make_job(job_type="fail")

        with (
            patch("phiacta.jobs.worker.JobRepository", return_value=mock_repo),
            patch.object(worker, "_handle_retry", new_callable=AsyncMock) as mock_retry,
        ):
            await worker._process_job(job)

        mock_repo.mark_failed.assert_awaited_once()
        mock_retry.assert_not_awaited()

    async def test_infra_error_triggers_retry(self) -> None:
        """JobInfraError triggers _handle_retry (retryable)."""
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={"infra": _InfraFailHandler()})
        factory, session = _mock_session_factory()
        worker._session_factory = factory

        job = _make_job(job_type="infra")

        with patch.object(worker, "_handle_retry", new_callable=AsyncMock) as mock_retry:
            await worker._process_job(job)

        mock_retry.assert_awaited_once()
        assert "docker daemon unreachable" in mock_retry.call_args[0][1]

    async def test_success_marks_completed(self) -> None:
        """Successful handler run marks job as completed and logs activity."""
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={"ok": _SuccessHandler()})
        factory, session = _mock_session_factory()
        worker._session_factory = factory

        mock_repo = AsyncMock()
        mock_entity_repo = AsyncMock()
        mock_entity_repo.get_by_id = AsyncMock(return_value=MagicMock())  # truthy entity
        mock_activity_repo = AsyncMock()
        job = _make_job(job_type="ok")

        with (
            patch("phiacta.jobs.worker.JobRepository", return_value=mock_repo),
            patch("phiacta.jobs.worker.EntityRepository", return_value=mock_entity_repo),
            patch("phiacta.jobs.worker.ActivityRepository", return_value=mock_activity_repo),
        ):
            await worker._process_job(job)

        # Verify mark_completed with handler result
        mock_repo.mark_completed.assert_awaited_once()
        result = mock_repo.mark_completed.call_args[0][1]
        assert result["status"] == "ok"

        # Verify activity logging was called with correct arguments
        mock_entity_repo.get_by_id.assert_awaited_once_with(job.id)
        mock_activity_repo.log.assert_awaited_once_with(
            actor_id=job.submitted_by,
            action="job.completed",
            entity_id=job.id,
            metadata={"job_type": job.job_type},
        )

    async def test_handler_writes_and_mark_completed_share_a_transaction(self) -> None:
        """Handler's session writes and mark_completed run in the same session.

        Regression test: previously the handler committed its result in one
        transaction and then mark_completed ran in a SEPARATE session. If
        the second commit failed, the handler's result was already
        persisted but the job was stuck running — permanently inconsistent.

        We assert that mark_completed is invoked on the SAME session
        object that the handler ran on, so a single commit covers both.
        """
        engine = AsyncMock()

        # Capture the session the handler sees via ctx.db.
        seen_handler_sessions: list[Any] = []

        class _CaptureHandler(JobHandler):
            async def run(
                self, input: dict[str, Any], ctx: JobContext,
            ) -> dict[str, Any]:
                seen_handler_sessions.append(ctx.db)
                return {"status": "ok"}

        worker = JobWorker(engine, handlers={"capture": _CaptureHandler()})

        # Each context manager entry yields a NEW session (so we can
        # detect if mark_completed is run against a different one).
        sessions_handed_out: list[AsyncMock] = []

        @asynccontextmanager
        async def _factory():
            session = AsyncMock()
            session.commit = AsyncMock()
            sessions_handed_out.append(session)
            yield session

        worker._session_factory = MagicMock(side_effect=_factory)

        seen_repo_sessions: list[Any] = []

        def _make_repo(s):
            seen_repo_sessions.append(s)
            return AsyncMock()

        mock_entity_repo = AsyncMock()
        mock_entity_repo.get_by_id = AsyncMock(return_value=None)

        with (
            patch("phiacta.jobs.worker.JobRepository", side_effect=_make_repo),
            patch("phiacta.jobs.worker.EntityRepository", return_value=mock_entity_repo),
            patch("phiacta.jobs.worker.ActivityRepository", return_value=AsyncMock()),
        ):
            await worker._process_job(_make_job(job_type="capture"))

        assert len(seen_handler_sessions) == 1, "handler ran exactly once"
        # Success path opens TWO sessions: one for handler+mark_completed
        # (same transaction), one for auxiliary activity logging (separate
        # so a failure there can't roll back the handler's result).
        assert len(sessions_handed_out) == 2, (
            "expected 2 sessions (handler+mark_completed, then activity); "
            "found %d" % len(sessions_handed_out)
        )
        assert len(seen_repo_sessions) == 1
        assert seen_repo_sessions[0] is seen_handler_sessions[0], (
            "mark_completed must use the handler's session, not a fresh one"
        )

    async def test_mark_completed_failure_rolls_back_handler_writes(self) -> None:
        """If mark_completed raises, the handler's session is NOT committed.

        Regression test: previously mark_completed ran in a separate
        session that was already committed for the result. Now they share
        a session, so a mark_completed failure rolls back the result
        write and the job ends up in 'failed' (handled by the outer
        except). The system stays in a consistent state.
        """
        engine = AsyncMock()

        # A handler that "writes" something to the session and returns.
        handler_session_holder: dict[str, Any] = {}

        class _WriteHandler(JobHandler):
            async def run(
                self, input: dict[str, Any], ctx: JobContext,
            ) -> dict[str, Any]:
                handler_session_holder["session"] = ctx.db
                return {"status": "ok"}

        worker = JobWorker(engine, handlers={"write": _WriteHandler()})

        # Each call to the session factory yields a fresh session.
        sessions_handed_out: list[AsyncMock] = []

        @asynccontextmanager
        async def _factory():
            session = AsyncMock()
            session.commit = AsyncMock()
            sessions_handed_out.append(session)
            yield session

        worker._session_factory = MagicMock(side_effect=_factory)

        # First JobRepository call (mark_completed on handler_session) raises.
        # Second JobRepository call (mark_failed on a fresh bookkeeping
        # session) captures so we can verify the failure path was hit.
        mark_completed_repo = AsyncMock()
        mark_completed_repo.mark_completed = AsyncMock(
            side_effect=RuntimeError("simulated DB failure on status update"),
        )
        mark_failed_repo = AsyncMock()

        repo_constructor_calls: list[Any] = []

        def _repo_factory(s):
            repo_constructor_calls.append(s)
            return mark_completed_repo if len(repo_constructor_calls) == 1 else mark_failed_repo

        mock_entity_repo = AsyncMock()
        mock_entity_repo.get_by_id = AsyncMock(return_value=None)

        with (
            patch("phiacta.jobs.worker.JobRepository", side_effect=_repo_factory),
            patch("phiacta.jobs.worker.EntityRepository", return_value=mock_entity_repo),
            patch("phiacta.jobs.worker.ActivityRepository", return_value=AsyncMock()),
        ):
            await worker._process_job(_make_job(job_type="write"))

        # The handler session was NEVER successfully committed (because
        # mark_completed raised before commit was reached). This is what
        # rolls back any handler-staged writes (e.g. compiled PDF blob).
        handler_session = handler_session_holder["session"]
        handler_session.commit.assert_not_awaited()

        # mark_completed was attempted on the handler session.
        mark_completed_repo.mark_completed.assert_awaited_once()

        # The job was then marked failed via the outer except handler in
        # a separate bookkeeping session — keeping the row consistent.
        mark_failed_repo.mark_failed.assert_awaited_once()
        # Two distinct sessions: handler+mark_completed (rolled back) and
        # the bookkeeping session for mark_failed (committed).
        assert len(sessions_handed_out) == 2
        assert sessions_handed_out[0] is not sessions_handed_out[1]
        assert sessions_handed_out[1].commit.await_count == 1, (
            "mark_failed bookkeeping session must commit"
        )


# --- _handle_retry ----------------------------------------------------------


class TestHandleRetry:
    """Test _handle_retry delegates to repo.mark_retry correctly."""

    async def test_retry_below_threshold(self) -> None:
        """Job with attempts below max → mark_retry called, mark_failed not."""
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        factory, session = _mock_session_factory()
        worker._session_factory = factory

        mock_repo = AsyncMock()
        job = _make_job(attempts=0, max_attempts=3)

        with patch("phiacta.jobs.worker.JobRepository", return_value=mock_repo):
            await worker._handle_retry(job, "infra error")

        mock_repo.mark_retry.assert_awaited_once()
        args = mock_repo.mark_retry.call_args[0]
        assert args[0] == job.id
        assert args[1] == "infra error"
        mock_repo.mark_failed.assert_not_awaited()

    async def test_retry_at_threshold_delegates_to_repo(self) -> None:
        """Job at max attempts → mark_retry still called (repo decides fail)."""
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        factory, session = _mock_session_factory()
        worker._session_factory = factory

        mock_repo = AsyncMock()
        job = _make_job(attempts=2, max_attempts=3)

        with patch("phiacta.jobs.worker.JobRepository", return_value=mock_repo):
            await worker._handle_retry(job, "final infra error")

        # Worker always calls mark_retry; the repository decides retry vs fail
        mock_repo.mark_retry.assert_awaited_once()
        args = mock_repo.mark_retry.call_args[0]
        assert args[0] == job.id
        assert args[1] == "final infra error"

