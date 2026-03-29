# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Meta-test: every route with {entry_id} rejects private entries for non-owners.

Discovers all GET routes containing ``{entry_id}`` in the FastAPI app,
creates a private entry, and asserts that a non-owner receives 403
on each route. This catches any new endpoint that forgets visibility checks.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.main import app
from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


async def set_entry_visibility(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    visibility: str,
) -> None:
    """Set an entry's visibility directly in the DB."""
    from phiacta.core.models.entry import Entry

    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.visibility = visibility
        await session.commit()


def _get_entry_id_get_routes() -> list[str]:
    """Discover all GET routes containing {entry_id} in their path."""
    routes = []
    for route in app.routes:
        if not hasattr(route, "methods") or "GET" not in route.methods:
            continue
        path = getattr(route, "path", "")
        if "{entry_id}" in path:
            routes.append(path)
    return sorted(set(routes))


_SUB_RESOURCE_DEFAULTS = {
    "{path:path}": ".phiacta/content.md",
    "{number}": "1",
    "{sha}": "a" * 40,
}


def _fill_path(path_template: str, entry_id: str) -> str:
    """Fill a route template with the entry ID and default sub-resource IDs."""
    result = path_template.replace("{entry_id}", entry_id)
    for placeholder, default in _SUB_RESOURCE_DEFAULTS.items():
        result = result.replace(placeholder, default)
    if "{" in result:
        return ""
    return result


class TestVisibilityMeta:
    """Meta-test: all GET {entry_id} routes return 403 for private entries (non-owner)."""

    async def test_all_entry_get_routes_block_private_for_non_owner(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        owner = await register_user(client, handle="vmeta-owner")
        owner_token = owner["access_token"]
        entry = await create_entry(client, owner_token, title="Visibility Meta Test")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        await set_entry_visibility(e2e_session_factory, entry_id, "private")

        other = await register_user(client, handle="vmeta-other")
        other_token = other["access_token"]

        routes = _get_entry_id_get_routes()
        assert routes, "No GET routes with {entry_id} found -- test is broken"

        failures = []
        for route_template in routes:
            path = _fill_path(route_template, entry_id)
            if not path:
                continue

            resp = await client.get(path, headers=auth_header(other_token))
            if resp.status_code != 403:
                failures.append(
                    f"{route_template} -> {resp.status_code} (expected 403) "
                    f"for non-owner"
                )

            resp = await client.get(path)
            if resp.status_code != 403:
                failures.append(
                    f"{route_template} -> {resp.status_code} (expected 403) "
                    f"for unauthenticated"
                )

        if failures:
            msg = "Private entry leaked on GET routes:\n" + "\n".join(
                f"  - {f}" for f in failures
            )
            pytest.fail(msg)

    async def test_all_entry_get_routes_allow_owner(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
        fake_git: FakeGitService,
    ) -> None:
        """Owner should be able to access all GET {entry_id} routes for their private entry."""
        owner = await register_user(client, handle="vmeta-own-ok")
        owner_token = owner["access_token"]
        entry = await create_entry(client, owner_token, title="Visibility Meta Owner")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")

        eid = UUID(entry_id)
        fake_git.files[(eid, ".phiacta/content.md")] = b"# Content"

        await set_entry_visibility(e2e_session_factory, entry_id, "private")

        routes = _get_entry_id_get_routes()

        failures = []
        for route_template in routes:
            path = _fill_path(route_template, entry_id)
            if not path:
                continue

            resp = await client.get(path, headers=auth_header(owner_token))
            if resp.status_code in (401, 403):
                failures.append(
                    f"{route_template} -> {resp.status_code} "
                    f"(owner should not be blocked)"
                )

        if failures:
            msg = "Owner blocked from their own private entry:\n" + "\n".join(
                f"  - {f}" for f in failures
            )
            pytest.fail(msg)
