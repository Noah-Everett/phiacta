# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Meta-test: every route with {entry_id} rejects archived entries for non-owners.

Discovers all GET routes containing ``{entry_id}`` in the FastAPI app,
creates an archived entry, and asserts that a non-owner receives 404
on each route. This catches any new endpoint that forgets the archive
visibility check.
"""

from __future__ import annotations

import re

import httpx
import pytest

from phiacta.main import app
from tests.e2e.conftest import (
    FakeGitService,
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
    set_entry_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


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


# Paths that need a sub-resource ID filled in (number, sha, etc.)
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
    # If there are still unfilled params, skip this route
    if "{" in result:
        return ""
    return result


class TestArchiveVisibilityMeta:
    """Meta-test: all GET {entry_id} routes return 404 for archived entries."""

    async def test_all_entry_get_routes_block_archived_for_non_owner(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory,
        fake_git: FakeGitService,
    ) -> None:
        # Create entry as owner, set ready, then archive
        owner = await register_user(client, handle="meta-owner")
        owner_token = owner["access_token"]
        entry = await create_entry(client, owner_token, title="Meta Test")
        entry_id = entry["id"]
        await set_entry_repo_status(e2e_session_factory, entry_id, "ready")
        await set_entry_status(e2e_session_factory, entry_id, "archived")

        # Register a different user
        other = await register_user(client, handle="meta-other")
        other_token = other["access_token"]

        routes = _get_entry_id_get_routes()
        assert routes, "No GET routes with {entry_id} found — test is broken"

        failures = []
        for route_template in routes:
            path = _fill_path(route_template, entry_id)
            if not path:
                continue

            # Non-owner with auth
            resp = await client.get(path, headers=auth_header(other_token))
            if resp.status_code != 404:
                failures.append(
                    f"{route_template} -> {resp.status_code} (expected 404) "
                    f"for non-owner"
                )

            # Unauthenticated
            resp = await client.get(path)
            if resp.status_code != 404:
                failures.append(
                    f"{route_template} -> {resp.status_code} (expected 404) "
                    f"for unauthenticated"
                )

        if failures:
            msg = "Archived entry leaked on GET routes:\n" + "\n".join(
                f"  - {f}" for f in failures
            )
            pytest.fail(msg)
