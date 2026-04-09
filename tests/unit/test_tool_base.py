# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for the JobHandler ABC, JobContext, and exception hierarchy."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from phiacta.tools.base import (
    JobContext,
    JobError,
    JobHandler,
    JobInfraError,
    JobUserError,
)


# --- JobHandler ABC -------------------------------------------------------


class _EchoHandler(JobHandler):
    """Minimal concrete handler for testing."""

    async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return {"echo": input}


class _FileTriggeredHandler(JobHandler):
    file_triggered = True

    async def run(self, input: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        return {}


class TestJobHandlerABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            JobHandler()  # type: ignore[abstract]

    def test_concrete_handler_instantiates(self) -> None:
        handler = _EchoHandler()
        assert handler.file_triggered is False

    async def test_run_returns_result(self) -> None:
        handler = _EchoHandler()
        ctx = JobContext(db=AsyncMock(), user_id=uuid4(), sandbox=AsyncMock())
        result = await handler.run({"key": "value"}, ctx)
        assert result == {"echo": {"key": "value"}}

    def test_file_triggered_default_false(self) -> None:
        assert _EchoHandler.file_triggered is False

    def test_file_triggered_override(self) -> None:
        assert _FileTriggeredHandler.file_triggered is True


# --- JobContext -------------------------------------------------------------


class TestJobContext:
    def test_fields(self) -> None:
        db = AsyncMock()
        user_id = uuid4()
        sandbox = AsyncMock()
        ctx = JobContext(db=db, user_id=user_id, sandbox=sandbox)
        assert ctx.db is db
        assert ctx.user_id == user_id
        assert ctx.sandbox is sandbox


# --- Exception hierarchy ----------------------------------------------------


class TestExceptions:
    def test_tool_error_is_exception(self) -> None:
        assert issubclass(JobError, Exception)

    def test_infra_error_is_tool_error(self) -> None:
        assert issubclass(JobInfraError, JobError)

    def test_user_error_is_tool_error(self) -> None:
        assert issubclass(JobUserError, JobError)

    def test_infra_error_not_user_error(self) -> None:
        assert not issubclass(JobInfraError, JobUserError)

    def test_catch_tool_error_catches_infra(self) -> None:
        with pytest.raises(JobError):
            raise JobInfraError("docker down")

    def test_catch_tool_error_catches_user(self) -> None:
        with pytest.raises(JobError):
            raise JobUserError("bad input")
