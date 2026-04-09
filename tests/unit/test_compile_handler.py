# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for CompileHandler and the compiled_content on_ingest hook."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from phiacta.extensions.compiled_content.handler import CompileHandler
from phiacta.jobs.models import Job  # noqa: F401 — registers table with Base.metadata
from phiacta.tools.base import JobContext, JobInfraError, JobUserError


# --- Helpers ----------------------------------------------------------------


def _make_ctx(db: AsyncMock | None = None) -> JobContext:
    return JobContext(
        db=db or AsyncMock(),
        user_id=uuid4(),
        sandbox=MagicMock(),
    )


def _make_entry(entry_id=None, head_sha="abc123"):
    entry = MagicMock()
    entry.id = entry_id or uuid4()
    entry.created_by = uuid4()
    entry.current_head_sha = head_sha
    return entry


@dataclass
class FakeCompileResult:
    success: bool
    log: str
    pdf_bytes: bytes | None = None
    no_source: bool = False


# --- CompileHandler tests ---------------------------------------------------


class TestCompileHandlerSuccess:
    async def test_compiles_and_stores_pdf(self) -> None:
        handler = CompileHandler()
        entry = _make_entry()
        ctx = _make_ctx()

        mock_repo = AsyncMock()
        mock_entry_repo = AsyncMock()
        mock_entry_repo.get_by_id.return_value = entry

        result = FakeCompileResult(
            success=True, log="ok", pdf_bytes=b"%PDF-fake",
        )

        with (
            patch(
                "phiacta.extensions.compiled_content.handler.EntryRepository",
                return_value=mock_entry_repo,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.CompiledContentRepository",
                return_value=mock_repo,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.compile_entry",
                return_value=result,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.ForgejoGitService",
            ),
        ):
            out = await handler.run({"entry_id": str(entry.id)}, ctx)

        assert out["status"] == "compiled"
        assert out["file_size"] == len(b"%PDF-fake")
        assert out["source_sha"] == "abc123"
        mock_repo.upsert.assert_awaited_once()


class TestCompileHandlerSkips:
    async def test_skips_when_entry_deleted(self) -> None:
        handler = CompileHandler()
        ctx = _make_ctx()

        mock_entry_repo = AsyncMock()
        mock_entry_repo.get_by_id.return_value = None

        with patch(
            "phiacta.extensions.compiled_content.handler.EntryRepository",
            return_value=mock_entry_repo,
        ):
            out = await handler.run({"entry_id": str(uuid4())}, ctx)

        assert out["status"] == "skipped"
        assert out["reason"] == "entry_not_found"

    async def test_skips_when_no_latex_source(self) -> None:
        handler = CompileHandler()
        entry = _make_entry()
        ctx = _make_ctx()

        mock_entry_repo = AsyncMock()
        mock_entry_repo.get_by_id.return_value = entry

        result = FakeCompileResult(success=False, log="", no_source=True)

        with (
            patch(
                "phiacta.extensions.compiled_content.handler.EntryRepository",
                return_value=mock_entry_repo,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.compile_entry",
                return_value=result,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.ForgejoGitService",
            ),
        ):
            out = await handler.run({"entry_id": str(entry.id)}, ctx)

        assert out["status"] == "skipped"
        assert out["reason"] == "no_latex_source"

    async def test_skips_when_sha_is_stale(self) -> None:
        handler = CompileHandler()
        entry = _make_entry(head_sha="old_sha")
        ctx = _make_ctx()

        # First call returns entry with old_sha, second returns entry with new_sha
        entry_now = _make_entry(entry_id=entry.id, head_sha="new_sha")
        mock_entry_repo = AsyncMock()
        mock_entry_repo.get_by_id.side_effect = [entry, entry_now]

        mock_compiled_repo = AsyncMock()
        result = FakeCompileResult(
            success=True, log="ok", pdf_bytes=b"%PDF-fake",
        )

        with (
            patch(
                "phiacta.extensions.compiled_content.handler.EntryRepository",
                return_value=mock_entry_repo,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.CompiledContentRepository",
                return_value=mock_compiled_repo,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.compile_entry",
                return_value=result,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.ForgejoGitService",
            ),
        ):
            out = await handler.run({"entry_id": str(entry.id)}, ctx)

        assert out["status"] == "skipped"
        assert out["reason"] == "stale_sha"
        mock_compiled_repo.upsert.assert_not_awaited()


class TestCompileHandlerErrors:
    async def test_compilation_failure_raises_user_error(self) -> None:
        handler = CompileHandler()
        entry = _make_entry()
        ctx = _make_ctx()

        mock_entry_repo = AsyncMock()
        mock_entry_repo.get_by_id.return_value = entry

        result = FakeCompileResult(success=False, log="! Undefined control sequence")

        with (
            patch(
                "phiacta.extensions.compiled_content.handler.EntryRepository",
                return_value=mock_entry_repo,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.compile_entry",
                return_value=result,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.ForgejoGitService",
            ),
        ):
            with pytest.raises(JobUserError, match="LaTeX compilation failed"):
                await handler.run({"entry_id": str(entry.id)}, ctx)

    async def test_forgejo_unavailable_raises_infra_error(self) -> None:
        handler = CompileHandler()
        entry = _make_entry()
        ctx = _make_ctx()

        mock_entry_repo = AsyncMock()
        mock_entry_repo.get_by_id.return_value = entry

        from phiacta.core.services.git_service import ForgejoUnavailableError

        with (
            patch(
                "phiacta.extensions.compiled_content.handler.EntryRepository",
                return_value=mock_entry_repo,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.compile_entry",
                side_effect=ForgejoUnavailableError("connection refused"),
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.ForgejoGitService",
            ),
        ):
            with pytest.raises(JobInfraError, match="Git service unavailable"):
                await handler.run({"entry_id": str(entry.id)}, ctx)

    async def test_missing_tectonic_raises_infra_error(self) -> None:
        handler = CompileHandler()
        entry = _make_entry()
        ctx = _make_ctx()

        mock_entry_repo = AsyncMock()
        mock_entry_repo.get_by_id.return_value = entry

        with (
            patch(
                "phiacta.extensions.compiled_content.handler.EntryRepository",
                return_value=mock_entry_repo,
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.compile_entry",
                side_effect=FileNotFoundError("tectonic"),
            ),
            patch(
                "phiacta.extensions.compiled_content.handler.ForgejoGitService",
            ),
        ):
            with pytest.raises(JobInfraError, match="tectonic binary not found"):
                await handler.run({"entry_id": str(entry.id)}, ctx)


# --- on_ingest hook tests ---------------------------------------------------


class TestOnIngestHook:
    async def _create_entry(self, db_session):
        from phiacta.core.models.entry import Entry
        from phiacta.core.models.user import User
        from tests.conftest import make_entry, make_user

        user = User(**make_user())
        db_session.add(user)
        await db_session.flush()
        entry = Entry(**make_entry(created_by=user.id))
        db_session.add(entry)
        await db_session.flush()
        return entry, user

    async def _count_jobs(self, db_session, entry_id=None):
        from sqlalchemy import select, func
        from phiacta.jobs.models import Job

        stmt = select(func.count()).select_from(Job)
        if entry_id is not None:
            stmt = stmt.where(Job.entity_id == entry_id)
        result = await db_session.execute(stmt)
        return result.scalar()

    async def test_submits_job_for_latex_content(self, db_session) -> None:
        from phiacta.extensions.compiled_content import on_ingest
        from phiacta.jobs.models import Job
        from sqlalchemy import select

        entry, user = await self._create_entry(db_session)

        await on_ingest(
            entry.id,
            "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}",
            {},
            db_session,
        )

        result = await db_session.execute(
            select(Job).where(Job.entity_id == entry.id)
        )
        job = result.scalar_one()
        assert job.job_type == "compiled_content"
        assert job.input == {"entry_id": str(entry.id)}
        assert job.submitted_by == user.id
        assert job.timeout_seconds == 180
        assert job.status == "pending"

    async def test_skips_plain_markdown(self, db_session) -> None:
        from phiacta.extensions.compiled_content import on_ingest

        entry, _ = await self._create_entry(db_session)
        await on_ingest(entry.id, "# Just markdown", {}, db_session)
        assert await self._count_jobs(db_session, entry.id) == 0

    async def test_submits_job_when_content_is_none(self, db_session) -> None:
        """content=None might be a multi-file LaTeX project."""
        from phiacta.extensions.compiled_content import on_ingest

        entry, _ = await self._create_entry(db_session)
        await on_ingest(entry.id, None, {}, db_session)
        assert await self._count_jobs(db_session, entry.id) == 1

    async def test_skips_when_entry_not_found(self, db_session) -> None:
        from phiacta.extensions.compiled_content import on_ingest

        await on_ingest(uuid4(), None, {}, db_session)
        assert await self._count_jobs(db_session) == 0
