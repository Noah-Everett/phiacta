# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for JobWorker — poll loop, dispatch, and error handling.

Uses mocked session factories and handlers to test worker logic in isolation.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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


# --- Job types filtering ---------------------------------------------------


class TestJobTypes:
    def test_stores_job_types(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(
            engine,
            handlers={"latex": _SuccessHandler()},
            job_types=["latex"],
        )
        assert worker._job_types == ["latex"]

    def test_default_no_filter(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        assert worker._job_types is None


# --- No _waiters or _notify ------------------------------------------------


class TestNoInMemoryEvents:
    """Verify that the in-memory event mechanism has been removed."""

    def test_no_waiters_attribute(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        assert not hasattr(worker, "_waiters")

    def test_no_notify_method(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        assert not hasattr(worker, "_notify")

    def test_no_submit_and_wait_method(self) -> None:
        engine = AsyncMock()
        worker = JobWorker(engine, handlers={})
        assert not hasattr(worker, "submit_and_wait")
