# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for auto-composed entry responses (NEV-279)."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import phiacta.extensions.metadata.models  # noqa: F401
import phiacta.extensions.types.models  # noqa: F401
import phiacta.extensions.tags.models  # noqa: F401
import phiacta.extensions.references.models  # noqa: F401

from tests.e2e.conftest import (
    auth_header,
    create_entry,
    register_user,
    set_entry_repo_status,
)

type AuthedFixture = tuple[httpx.AsyncClient, dict, str]


@pytest.fixture(autouse=True)
def _mount_extension_routers(client: httpx.AsyncClient) -> None:
    from phiacta.extensions.metadata import router as mr
    from phiacta.extensions.types import router as tr
    from phiacta.extensions.tags import router as tagr
    from phiacta.extensions.references import router as refr
    from phiacta.main import app as _app
    _app.include_router(mr, prefix="/v1/extensions/metadata", tags=["metadata"])
    _app.include_router(tr, prefix="/v1/extensions/types", tags=["types"])
    _app.include_router(tagr, prefix="/v1/extensions/tags", tags=["tags"])
    _app.include_router(refr, prefix="/v1/extensions/references", tags=["references"])
    yield  # type: ignore[misc]
    _app.routes[:] = [
        r for r in _app.routes
        if not (
            hasattr(r, "path")
            and any(
                r.path.startswith(p)
                for p in (
                    "/v1/extensions/metadata",
                    "/v1/extensions/types",
                    "/v1/extensions/tags",
                    "/v1/extensions/references",
                )
            )
        )
    ]


@pytest.fixture
async def authed(client: httpx.AsyncClient) -> AuthedFixture:
    auth = await register_user(client, username=f"compose-{uuid4().hex[:8]}")
    return client, auth["user"], auth["access_token"]


@pytest.fixture
async def ready_entry(
    authed: AuthedFixture,
    e2e_session_factory: async_sessionmaker[AsyncSession],
) -> tuple[AuthedFixture, dict]:
    client, _, token = authed
    entry = await create_entry(
        client, token, title="Compose Test", entry_type="claim",
    )
    await set_entry_repo_status(e2e_session_factory, entry["id"], "ready")
    return authed, entry


# ---------------------------------------------------------------------------
# Detail response composition
# ---------------------------------------------------------------------------


class TestDetailComposition:
    async def test_detail_includes_all_extension_fields(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        # Set tags via extension endpoint
        await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["physics", "math"]},
            headers=auth_header(token),
        )

        data = (await client.get(f"/v1/entries/{entry_id}")).json()
        assert data["title"] == "Compose Test"
        assert data["entry_type"] == "claim"
        assert sorted(data["tags"]) == ["math", "physics"]
        assert data["references"] == []

    async def test_detail_includes_references(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        # Create a second entry to reference
        target = await create_entry(client, token, title="Target Entry")

        # Create a reference
        resp = await client.post(
            f"/v1/extensions/references/{entry_id}",
            json={
                "target_entry_id": target["id"],
                "rel": "cites",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 201

        data = (await client.get(f"/v1/entries/{entry_id}")).json()
        assert len(data["references"]) == 1
        ref = data["references"][0]
        assert ref["rel"] == "cites"
        assert ref["to_entity_id"] == target["id"]


# ---------------------------------------------------------------------------
# List response composition
# ---------------------------------------------------------------------------


class TestListComposition:
    async def test_list_includes_metadata_types_tags(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["tag1"]},
            headers=auth_header(token),
        )

        items = (await client.get("/v1/entries")).json()["items"]
        item = next(i for i in items if i["id"] == entry_id)
        assert item["title"] == "Compose Test"
        assert item["entry_type"] == "claim"
        assert item["tags"] == ["tag1"]

    async def test_list_excludes_references_by_default(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = ready_entry
        items = (await client.get("/v1/entries")).json()["items"]
        item = next(i for i in items if i["id"] == entry["id"])
        # references has include_in_list=False, and EntryListItem doesn't
        # have a references field, so it should not appear
        assert "references" not in item


# ---------------------------------------------------------------------------
# Include / exclude filtering
# ---------------------------------------------------------------------------


class TestFieldFiltering:
    async def test_exclude_tags(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        entry_id = entry["id"]

        await client.put(
            f"/v1/extensions/tags/{entry_id}",
            json={"tags": ["excluded"]},
            headers=auth_header(token),
        )

        data = (await client.get(
            f"/v1/entries/{entry_id}", params={"exclude": "tags"},
        )).json()
        assert data["title"] == "Compose Test"
        assert data.get("tags") is None

    async def test_include_only_title(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = ready_entry
        data = (await client.get(
            f"/v1/entries/{entry['id']}", params={"include": "title"},
        )).json()
        assert data["title"] == "Compose Test"
        # Other extension fields should be null (providers skipped)
        assert data.get("entry_type") is None
        assert data.get("tags") is None

    async def test_include_and_exclude_returns_422(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = ready_entry
        resp = await client.get(
            f"/v1/entries/{entry['id']}",
            params={"include": "title", "exclude": "tags"},
        )
        assert resp.status_code == 422

    async def test_list_exclude_entry_type(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, _), entry = ready_entry
        items = (await client.get(
            "/v1/entries", params={"exclude": "entry_type"},
        )).json()["items"]
        item = next(i for i in items if i["id"] == entry["id"])
        assert item["title"] == "Compose Test"
        assert item.get("entry_type") is None


# ---------------------------------------------------------------------------
# Unified PATCH write routing
# ---------------------------------------------------------------------------


class TestUnifiedPatch:
    async def test_patch_title_only(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Updated Title"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Title"

    async def test_patch_entry_type(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"entry_type": "theorem"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["entry_type"] == "theorem"

    async def test_patch_tags(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"tags": ["alpha", "beta"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert sorted(resp.json()["tags"]) == ["alpha", "beta"]

    async def test_patch_multiple_fields(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        """PATCH with fields from different providers in one request."""
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={
                "title": "Multi-Update",
                "entry_type": "definition",
                "tags": ["x"],
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Multi-Update"
        assert data["entry_type"] == "definition"
        assert data["tags"] == ["x"]

    async def test_patch_empty_body_returns_422(
        self, ready_entry: tuple[AuthedFixture, dict],
    ) -> None:
        (client, _, token), entry = ready_entry
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_patch_non_owner_returns_403(
        self,
        ready_entry: tuple[AuthedFixture, dict],
        client: httpx.AsyncClient,
    ) -> None:
        (_, _, _), entry = ready_entry
        other = await register_user(client, username=f"other-{uuid4().hex[:8]}")
        resp = await client.patch(
            f"/v1/entries/{entry['id']}",
            json={"title": "Hijack"},
            headers=auth_header(other["access_token"]),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    async def test_response_works_without_providers(
        self, client: httpx.AsyncClient,
    ) -> None:
        """Entry responses work even with no providers registered."""
        from phiacta.main import app as _app

        # Temporarily clear providers
        original = getattr(_app.state, "entry_data_providers", [])
        _app.state.entry_data_providers = []
        try:
            auth = await register_user(client, username=f"noprov-{uuid4().hex[:8]}")
            entry = await create_entry(client, auth["access_token"], title="Bare")
            data = (await client.get(f"/v1/entries/{entry['id']}")).json()
            assert data["id"] == entry["id"]
            # Extension fields should be null
            assert data.get("title") is None
            assert data.get("tags") is None
        finally:
            _app.state.entry_data_providers = original
