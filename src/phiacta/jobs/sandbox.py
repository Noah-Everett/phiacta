# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Docker sandbox — manages container lifecycle for sandboxed tool execution.

Uses the Docker CLI via asyncio subprocesses. No external Python
dependencies required beyond a working ``docker`` binary on ``$PATH``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from phiacta.jobs.security import SecurityPolicy

logger = logging.getLogger(__name__)

_PIPE = asyncio.subprocess.PIPE


@dataclass
class SandboxResult:
    """Result from running a sandboxed container."""

    exit_code: int
    stdout: str
    stderr: str
    files: dict[str, bytes] = field(default_factory=dict)


class Sandbox:
    """Runs tool code in isolated Docker containers.

    Security defaults: network disabled, read-only rootfs, all capabilities
    dropped, no new privileges, PID and memory limits.

    Input files are bind-mounted read-only at ``/input``.
    Output files should be written to ``/output`` (bind-mounted read-write).
    """

    async def run(
        self,
        *,
        image: str,
        command: list[str],
        files: dict[str, bytes] | None = None,
        security: SecurityPolicy | None = None,
        job_id: UUID | None = None,
    ) -> SandboxResult:
        """Create, run, and clean up a container. Returns stdout/stderr/files."""
        sec = security or SecurityPolicy()

        with TemporaryDirectory(prefix="phiacta-") as workdir:
            input_path = Path(workdir) / "input"
            output_path = Path(workdir) / "output"
            input_path.mkdir()
            output_path.mkdir()

            # Write input files to bind-mount directory
            if files:
                for name, data in files.items():
                    dest = input_path / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)

            container_id = await self._create_container(
                image=image,
                command=command,
                input_path=input_path,
                output_path=output_path,
                security=sec,
                job_id=job_id,
            )
            if container_id is None:
                return SandboxResult(exit_code=-1, stdout="", stderr="Failed to create container")

            try:
                return await self._run_container(container_id, output_path, sec)
            finally:
                await self._exec("docker", "rm", "-f", container_id)

    async def _create_container(
        self,
        *,
        image: str,
        command: list[str],
        input_path: Path,
        output_path: Path,
        security: SecurityPolicy,
        job_id: UUID | None,
    ) -> str | None:
        """``docker create`` with security constraints. Returns container ID."""
        cmd: list[str] = ["docker", "create"]

        # Security
        if security.network_disabled:
            cmd.append("--network=none")
        if security.read_only_rootfs:
            cmd.append("--read-only")
        cmd.append(f"--memory={security.memory_mb}m")
        cmd.append(f"--pids-limit={security.max_pids}")
        for cap in security.cap_drop:
            cmd.extend(["--cap-drop", cap])
        cmd.extend(["--security-opt", "no-new-privileges"])
        for tp in security.tmpfs_paths:
            cmd.extend(["--tmpfs", f"{tp}:rw,noexec,nosuid,size=64m"])

        # Bind mounts
        cmd.extend(["-v", f"{input_path}:/input:ro"])
        cmd.extend(["-v", f"{output_path}:/output:rw"])

        # Labels
        cmd.extend(["--label", "phiacta.managed=true"])
        if job_id:
            cmd.extend(["--label", f"phiacta.job_id={job_id}"])

        # Image + command
        cmd.append(image)
        cmd.extend(command)

        proc = await asyncio.create_subprocess_exec(*cmd, stdout=_PIPE, stderr=_PIPE)
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(
                "docker create failed (rc=%d): %s", proc.returncode, stderr.decode(errors="replace"),
            )
            return None

        return stdout.decode().strip()

    async def _run_container(
        self,
        container_id: str,
        output_path: Path,
        security: SecurityPolicy,
    ) -> SandboxResult:
        """Start container, wait for completion, collect results."""
        # Start
        rc = await self._exec("docker", "start", container_id)
        if rc != 0:
            return SandboxResult(exit_code=-1, stdout="", stderr="Failed to start container")

        # Wait with timeout
        wait_proc = await asyncio.create_subprocess_exec(
            "docker", "wait", container_id, stdout=_PIPE, stderr=_PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                wait_proc.communicate(), timeout=security.timeout_seconds,
            )
            exit_code = int(stdout.decode().strip())
        except asyncio.TimeoutError:
            logger.warning("Container %s timed out after %ds", container_id[:12], security.timeout_seconds)
            await self._exec("docker", "kill", container_id)
            return SandboxResult(
                exit_code=-1, stdout="", stderr=f"Timeout after {security.timeout_seconds}s",
            )

        # Collect logs
        log_proc = await asyncio.create_subprocess_exec(
            "docker", "logs", container_id, stdout=_PIPE, stderr=_PIPE,
        )
        stdout_log, stderr_log = await log_proc.communicate()

        # Collect output files from bind mount
        output_files: dict[str, bytes] = {}
        for p in output_path.rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(output_path))
                output_files[rel] = p.read_bytes()

        return SandboxResult(
            exit_code=exit_code,
            stdout=stdout_log.decode(errors="replace"),
            stderr=stderr_log.decode(errors="replace"),
            files=output_files,
        )

    async def kill_orphaned_containers(self) -> int:
        """Kill and remove all containers with the ``phiacta.managed`` label.

        Called on startup to clean up after a previous crash.
        """
        proc = await asyncio.create_subprocess_exec(
            "docker", "ps", "-q", "--filter", "label=phiacta.managed=true",
            stdout=_PIPE, stderr=_PIPE,
        )
        stdout, _ = await proc.communicate()
        container_ids = stdout.decode().strip().split("\n")
        container_ids = [c for c in container_ids if c]

        killed = 0
        for cid in container_ids:
            rc = await self._exec("docker", "rm", "-f", cid)
            if rc == 0:
                killed += 1
                logger.warning("Killed orphaned container %s", cid[:12])
        return killed

    async def close(self) -> None:
        """No persistent resources to clean up with CLI approach."""

    @staticmethod
    async def _exec(*cmd: str) -> int:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=_PIPE, stderr=_PIPE)
        await proc.communicate()
        return proc.returncode or 0
