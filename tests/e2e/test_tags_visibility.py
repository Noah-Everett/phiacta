# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for tag extension visibility with the new visibility model.

Tests that find_entries_by_tags excludes private entries for non-owners,
while owners see their private entries in tag search results.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def set_entry_visibility(
    session_factory: async_sessionmaker[AsyncSession],
    entry_id: str,
    visibility: str,
) -> None:
    """Set an entry's visibility directly in the DB."""
    from phiacta.core.models.entry import Entry
    from sqlalchemy import select

    async with session_factory() as session:
        result = await session.execute(
            select(Entry).where(Entry.id == UUID(entry_id))
        )
        entry = result.scalar_one()
        entry.visibility = visibility
        await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mount_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.tags import router as tagr
    from phiacta.extensions.types import router as tr
    from phiacta.main import app as _app

    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/types", tags=["types"])
    _app.include_router(tagr, prefix="/v1/extensions/tags", tags=["tags"])
    yield  # type: ignore[misc]
    prefixes = (
        "/v1/extensions/metadata", "/v1/extensions/types",
        "/v1/extensions/tags",
    )
    _app.routes[:] = [
        r for r in _app.routes
        if not (hasattr(r, "path") and any(r.path.startswith(p) for p in prefixes))
    ]


@pytest.fixture
async def owner(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"tagvis-owner-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def other_user(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, handle=f"tagvis-other-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def tagged_entries(
    owner: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> dict:
    """Create entries with tags and mixed visibility."""
    client, _, owner_token = owner

    public_physics = await create_entry(client, owner_token, title="Public Physics")
    await set_entry_repo_status(e2e_session_factory, public_physics["id"], "ready")
    resp = await client.put(
        f"/v1/extensions/tags/{public_physics['id']}",
        json={"tags": ["physics", "quantum"]},
        headers=auth_header(owner_token),
    )
    assert resp.status_code == 200

    private_physics = await create_entry(client, owner_token, title="Private Physics")
    await set_entry_repo_status(e2e_session_factory, private_physics["id"], "ready")
    resp = await client.put(
        f"/v1/extensions/tags/{private_physics['id']}",
        json={"tags": ["physics", "secret-research"]},
        headers=auth_header(owner_token),
    )
    assert resp.status_code == 200
    await set_entry_visibility(e2e_session_factory, private_physics["id"], "private")

    public_math = await create_entry(client, owner_token, title="Public Math")
    await set_entry_repo_status(e2e_session_factory, public_math["id"], "ready")
    resp = await client.put(
        f"/v1/extensions/tags/{public_math['id']}",
        json={"tags": ["math"]},
        headers=auth_header(owner_token),
    )
    assert resp.status_code == 200

    return {
        "public_physics": public_physics,
        "private_physics": private_physics,
        "public_math": public_math,
        "client": client,
        "owner_token": owner_token,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFindEntriesByTagsVisibility:
    """Private entries excluded from find_entries_by_tags for non-owners."""

    async def test_find_by_tag_excludes_private_for_non_owner(
        self, tagged_entries: dict, other_user: AuthedFixture,
    ) -> None:
        client = tagged_entries["client"]
        _, _, other_token = other_user
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "physics"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        entry_ids = {item["id"] for item in resp.json()["items"]}
        assert tagged_entries["public_physics"]["id"] in entry_ids
        assert tagged_entries["private_physics"]["id"] not in entry_ids

    async def test_find_by_tag_excludes_private_for_unauthenticated(
        self, tagged_entries: dict,
    ) -> None:
        client = tagged_entries["client"]
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "physics"},
        )
        assert resp.status_code == 200
        entry_ids = {item["id"] for item in resp.json()["items"]}
        assert tagged_entries["public_physics"]["id"] in entry_ids
        assert tagged_entries["private_physics"]["id"] not in entry_ids

    async def test_owner_sees_own_private_entries_in_tag_search(
        self, tagged_entries: dict,
    ) -> None:
        client = tagged_entries["client"]
        owner_token = tagged_entries["owner_token"]
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "physics"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        entry_ids = {item["id"] for item in resp.json()["items"]}
        assert tagged_entries["public_physics"]["id"] in entry_ids
        assert tagged_entries["private_physics"]["id"] in entry_ids

    async def test_find_by_private_only_tag_returns_empty_for_non_owner(
        self, tagged_entries: dict, other_user: AuthedFixture,
    ) -> None:
        client = tagged_entries["client"]
        _, _, other_token = other_user
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "secret-research"},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_owner_finds_entry_by_private_only_tag(
        self, tagged_entries: dict,
    ) -> None:
        client = tagged_entries["client"]
        owner_token = tagged_entries["owner_token"]
        resp = await client.get(
            "/v1/extensions/tags/entries",
            params={"tags": "secret-research"},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        entry_ids = {item["id"] for item in resp.json()["items"]}
        assert tagged_entries["private_physics"]["id"] in entry_ids


class TestListTagsVisibility:
    """Listing tags on a private entry returns 403 for non-owners."""

    async def test_list_tags_returns_403_for_non_owner(
        self, tagged_entries: dict, other_user: AuthedFixture,
    ) -> None:
        client = tagged_entries["client"]
        _, _, other_token = other_user
        private_id = tagged_entries["private_physics"]["id"]
        resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": private_id},
            headers=auth_header(other_token),
        )
        assert resp.status_code == 403

    async def test_list_tags_returns_403_for_unauthenticated(
        self, tagged_entries: dict,
    ) -> None:
        client = tagged_entries["client"]
        private_id = tagged_entries["private_physics"]["id"]
        resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": private_id},
        )
        assert resp.status_code == 403

    async def test_owner_can_list_tags_on_private_entry(
        self, tagged_entries: dict,
    ) -> None:
        client = tagged_entries["client"]
        owner_token = tagged_entries["owner_token"]
        private_id = tagged_entries["private_physics"]["id"]
        resp = await client.get(
            "/v1/extensions/tags/",
            params={"entry_id": private_id},
            headers=auth_header(owner_token),
        )
        assert resp.status_code == 200
        tag_names = [t["tag"] for t in resp.json()["tags"]]
        assert "physics" in tag_names
        assert "secret-research" in tag_names
