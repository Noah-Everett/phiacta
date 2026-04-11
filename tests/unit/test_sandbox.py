# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for the Docker sandbox — container creation, execution, and cleanup.

All Docker CLI calls are mocked via asyncio.create_subprocess_exec.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from phiacta.jobs.sandbox import Sandbox, SandboxResult
from phiacta.jobs.security import SecurityPolicy


def _mock_process(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> AsyncMock:
    """Create a mock subprocess with communicate() support."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    return proc


class TestSandboxResult:
    def test_defaults(self) -> None:
        r = SandboxResult(exit_code=0, stdout="hello", stderr="")
        assert r.exit_code == 0
        assert r.stdout == "hello"
        assert r.files == {}

    def test_with_files(self) -> None:
        r = SandboxResult(exit_code=0, stdout="", stderr="", files={"out.pdf": b"PDF"})
        assert r.files["out.pdf"] == b"PDF"


class TestSandboxCreateContainer:
    async def test_builds_correct_docker_create_args(self) -> None:
        """Verify that docker create is called with security constraints."""
        sandbox = Sandbox()
        container_id = "abc123def456"

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = _mock_process(
                stdout=container_id.encode() + b"\n"
            )

            sec = SecurityPolicy(memory_mb=1024, max_pids=32)
            result = await sandbox._create_container(
                image="test-image:latest",
                command=["echo", "hello"],
                input_path=Path("/tmp/input"),
                output_path=Path("/tmp/output"),
                security=sec,
                job_id=None,
            )

            assert result == container_id
            # Verify docker create was called
            call_args = mock_exec.call_args[0]
            assert call_args[0] == "docker"
            assert call_args[1] == "create"
            # Check security flags are present
            args_str = " ".join(str(a) for a in call_args)
            assert "--network=none" in args_str
            assert "--read-only" in args_str
            assert "--memory=1024m" in args_str
            assert "--pids-limit=32" in args_str
            assert "--cap-drop" in args_str
            assert "no-new-privileges" in args_str
            assert "phiacta.managed=true" in args_str

    async def test_includes_job_id_label(self) -> None:
        sandbox = Sandbox()
        job_id = uuid4()

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = _mock_process(stdout=b"container123\n")

            await sandbox._create_container(
                image="test:latest",
                command=["true"],
                input_path=Path("/tmp/in"),
                output_path=Path("/tmp/out"),
                security=SecurityPolicy(),
                job_id=job_id,
            )

            args_str = " ".join(str(a) for a in mock_exec.call_args[0])
            assert f"phiacta.job_id={job_id}" in args_str

    async def test_returns_none_on_failure(self) -> None:
        sandbox = Sandbox()

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = _mock_process(
                stderr=b"image not found", returncode=1,
            )

            result = await sandbox._create_container(
                image="nonexistent:latest",
                command=["true"],
                input_path=Path("/tmp/in"),
                output_path=Path("/tmp/out"),
                security=SecurityPolicy(),
                job_id=None,
            )
            assert result is None


class TestSandboxRun:
    async def test_returns_failure_when_create_fails(self) -> None:
        sandbox = Sandbox()

        with patch.object(sandbox, "_create_container", return_value=None):
            result = await sandbox.run(
                image="test:latest", command=["true"],
            )
            assert result.exit_code == -1
            assert "Failed to create container" in result.stderr

    async def test_writes_input_files(self) -> None:
        """Verify input files are written to the bind-mount directory."""
        sandbox = Sandbox()
        written_files: dict[str, bytes] = {}

        original_create = sandbox._create_container

        async def _capture_create(*, image, command, input_path, output_path, security, job_id):
            # Check that files were written to input_path
            for p in input_path.rglob("*"):
                if p.is_file():
                    written_files[str(p.relative_to(input_path))] = p.read_bytes()
            return None  # Abort after checking files

        with patch.object(sandbox, "_create_container", side_effect=_capture_create):
            await sandbox.run(
                image="test:latest",
                command=["true"],
                files={"main.tex": b"\\documentclass{article}", "figs/fig1.png": b"PNG"},
            )

        assert written_files["main.tex"] == b"\\documentclass{article}"
        assert written_files["figs/fig1.png"] == b"PNG"


class TestRunContainer:
    """Tests for Sandbox._run_container — start, wait, timeout, output."""

    async def test_start_failure(self) -> None:
        """docker start returning non-zero → immediate failure."""
        sandbox = Sandbox()

        with patch.object(sandbox, "_exec", new_callable=AsyncMock, return_value=1):
            result = await sandbox._run_container(
                "container123", Path("/tmp/output"), SecurityPolicy(),
            )

        assert result.exit_code == -1
        assert "Failed to start container" in result.stderr

    async def test_timeout_kills_container(self) -> None:
        """docker wait exceeding timeout → kill + timeout result."""
        sandbox = Sandbox()
        sec = SecurityPolicy(timeout_seconds=0.01)

        # docker start succeeds
        exec_calls: list[tuple] = []

        async def _mock_exec(*cmd):
            exec_calls.append(cmd)
            return 0

        # docker wait hangs forever
        hang_proc = AsyncMock()
        hang_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

        with (
            patch.object(sandbox, "_exec", side_effect=_mock_exec),
            patch("asyncio.create_subprocess_exec", return_value=hang_proc),
            patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()),
        ):
            result = await sandbox._run_container(
                "container123", Path("/tmp/output"), sec,
            )

        assert result.exit_code == -1
        assert "Timeout" in result.stderr
        # Verify docker kill was called
        kill_calls = [c for c in exec_calls if len(c) >= 2 and c[1] == "kill"]
        assert len(kill_calls) == 1

    async def test_collects_output_files(self, tmp_path: Path) -> None:
        """Output files in the bind mount appear in result.files."""
        sandbox = Sandbox()
        output_path = tmp_path / "output"
        output_path.mkdir()
        (output_path / "result.txt").write_bytes(b"hello")
        sub = output_path / "sub"
        sub.mkdir()
        (sub / "data.bin").write_bytes(b"\x00\x01")

        # docker start succeeds, docker wait returns 0, docker logs returns output
        async def _mock_exec(*cmd, **kwargs):
            if "wait" in cmd:
                return _mock_process(stdout=b"0\n")
            if "logs" in cmd:
                return _mock_process(stdout=b"log output", stderr=b"")
            return _mock_process()

        with (
            patch.object(sandbox, "_exec", new_callable=AsyncMock, return_value=0),
            patch("asyncio.create_subprocess_exec", side_effect=_mock_exec),
        ):
            result = await sandbox._run_container(
                "container123", output_path, SecurityPolicy(),
            )

        assert result.exit_code == 0
        assert result.files["result.txt"] == b"hello"
        assert result.files["sub/data.bin"] == b"\x00\x01"

    async def test_normal_execution(self, tmp_path: Path) -> None:
        """Normal run: start, wait, collect logs, return exit code."""
        sandbox = Sandbox()
        output_path = tmp_path / "output"
        output_path.mkdir()

        wait_proc = _mock_process(stdout=b"42\n")
        log_proc = _mock_process(stdout=b"stdout log", stderr=b"stderr log")

        call_count = 0

        async def _mock_exec(*cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "wait" in cmd:
                return wait_proc
            if "logs" in cmd:
                return log_proc
            return _mock_process()

        with (
            patch.object(sandbox, "_exec", new_callable=AsyncMock, return_value=0),
            patch("asyncio.create_subprocess_exec", side_effect=_mock_exec),
        ):
            result = await sandbox._run_container(
                "container123", output_path, SecurityPolicy(),
            )

        assert result.exit_code == 42
        assert "stdout log" in result.stdout
        assert "stderr log" in result.stderr


class TestSandboxKillOrphans:
    async def test_kills_listed_containers(self) -> None:
        sandbox = Sandbox()

        async def _mock_exec(*cmd, **kwargs):
            proc = _mock_process()
            if cmd[0] == "docker" and cmd[1] == "ps":
                proc.communicate = AsyncMock(return_value=(b"abc123\ndef456\n", b""))
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=_mock_exec):
            killed = await sandbox.kill_orphaned_containers()

        assert killed == 2

    async def test_no_orphans(self) -> None:
        sandbox = Sandbox()

        async def _mock_exec(*cmd, **kwargs):
            return _mock_process(stdout=b"\n")

        with patch("asyncio.create_subprocess_exec", side_effect=_mock_exec):
            killed = await sandbox.kill_orphaned_containers()
            assert killed == 0
