# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Standalone worker entrypoint — runs JobWorker without FastAPI.

Usage:
    python -m phiacta.jobs.run_worker

Environment variables:
    JOB_TYPES   JSON list of job types to handle (e.g. '["compiled_content"]').
                If unset, handles all registered job types.
    All standard phiacta env vars (DATABASE_URL, FORGEJO_*, ENABLED_PLUGINS, etc.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys

from phiacta.config import get_settings
from phiacta.core.db.session import get_engine
from phiacta.jobs.worker import start_job_worker
from phiacta.plugin import PluginRegistry

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        stream=sys.stderr,
    )


def _parse_job_types() -> list[str] | None:
    raw = os.environ.get("JOB_TYPES")
    if not raw:
        return None
    try:
        types = json.loads(raw)
        if isinstance(types, list) and all(isinstance(t, str) for t in types):
            return types
    except json.JSONDecodeError:
        pass
    logger.error("JOB_TYPES must be a JSON list of strings, got: %r", raw)
    sys.exit(1)


async def _main() -> None:
    _configure_logging()

    job_types = _parse_job_types()
    logger.info("Worker starting (job_types=%s)", job_types or "all")

    # Discover plugins to find job handlers
    settings = get_settings()
    registry = PluginRegistry(enabled_plugins=settings.enabled_plugins)
    registry.discover()
    registry.resolve_dependencies()

    handlers = registry.get_job_handlers()
    # If job_types is set, filter handlers to only those types
    if job_types is not None:
        handlers = {k: v for k, v in handlers.items() if k in job_types}

    engine = get_engine()
    worker = await start_job_worker(engine, handlers=handlers, job_types=job_types)

    # Wait for shutdown signal
    stop_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await stop_event.wait()

    await worker.stop()
    await engine.dispose()
    logger.info("Worker shut down cleanly")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
