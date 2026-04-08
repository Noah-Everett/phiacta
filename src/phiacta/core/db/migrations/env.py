# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from phiacta.config import get_settings

# Import all models so autogenerate can detect them.
import phiacta.core.models  # noqa: F401
import phiacta.extensions.compiled_content.models  # noqa: F401
import phiacta.jobs.models  # noqa: F401
from phiacta.core.models.base import Base

# Alembic Config object
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_version_locations() -> list[str]:
    """Build version_locations from core + all plugin migration dirs.

    Always includes ALL plugin migration directories regardless of
    enabled_plugins — migration state is about the DB schema, not
    runtime config.
    """
    import phiacta

    package_root = Path(phiacta.__file__).parent

    # Always include core migrations
    locations = [str(package_root / "core" / "db" / "migrations" / "versions")]

    # Scan ALL plugin directories for migrations/ subdirs
    for plugin_dir_name in ("extensions", "views", "tools"):
        plugin_base = package_root / plugin_dir_name
        if not plugin_base.is_dir():
            continue
        for child in sorted(plugin_base.iterdir()):
            if not child.is_dir():
                continue
            migrations_dir = child / "migrations"
            if migrations_dir.is_dir():
                locations.append(str(migrations_dir))

    return locations


def get_url() -> str:
    """Read the database URL from settings."""
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_locations=_get_version_locations(),
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    """Execute migrations within a connection context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_locations=_get_version_locations(),
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
