# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for entry ref endpoints."""

from __future__ import annotations

from typing import TypeAlias
from uuid import uuid4

import httpx
import pytest

from tests.e2e.conftest import auth_header, register_user

TwoEntriesFixture: TypeAlias = tuple[httpx.AsyncClient, str, str, str]


@pytest.fixture
async def two_entries(
    client: httpx.AsyncClient,
) -> TwoEntriesFixture:
    """Create a user and two entries. Returns (client, entry_a_id, entry_b_id, token)."""
    uid = uuid4().hex[:8]
    auth = await register_user(client, handle=f"ref-{uid}")
    token = auth["access_token"]
    headers = auth_header(token)

    resp_a = await client.post("/v1/entries", json={"title": "Entry A"}, headers=headers)
    resp_b = await client.post("/v1/entries", json={"title": "Entry B"}, headers=headers)

    return client, resp_a.json()["id"], resp_b.json()["id"], token


class TestCreateEntryRef:
    async def test_create_ref(self, two_entries: TwoEntriesFixture) -> None:
        client, entry_a, entry_b, token = two_entries
        resp = await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a,
            "to_entry_id": entry_b,
            "rel": "supports",
        }, headers=auth_header(token))
        assert resp.status_code == 201
        data = resp.json()
        assert data["from_entry_id"] == entry_a
        assert data["to_entry_id"] == entry_b
        assert data["rel"] == "supports"

    async def test_create_ref_with_note(self, two_entries: TwoEntriesFixture) -> None:
        client, entry_a, entry_b, token = two_entries
        resp = await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a,
            "to_entry_id": entry_b,
            "rel": "derives",
            "note": "Derived via Noether's theorem",
        }, headers=auth_header(token))
        assert resp.status_code == 201
        assert resp.json()["note"] == "Derived via Noether's theorem"

    async def test_create_ref_unauthenticated(self, two_entries: TwoEntriesFixture) -> None:
        client, entry_a, entry_b, _ = two_entries
        resp = await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a,
            "to_entry_id": entry_b,
            "rel": "supports",
        })
        assert resp.status_code == 401

    async def test_create_self_ref_rejected(self, two_entries: TwoEntriesFixture) -> None:
        """Self-referential edges are rejected by the ck_entry_refs_no_self_ref constraint."""
        client, entry_a, _, token = two_entries
        resp = await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a,
            "to_entry_id": entry_a,
            "rel": "supports",
        }, headers=auth_header(token))
        assert resp.status_code == 422
        assert "Self-referential" in resp.json()["detail"]

    async def test_create_ref_nonexistent_entry(self, two_entries: TwoEntriesFixture) -> None:
        """Referencing a nonexistent entry ID should return 422."""
        client, entry_a, _, token = two_entries
        resp = await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a,
            "to_entry_id": str(uuid4()),
            "rel": "supports",
        }, headers=auth_header(token))
        assert resp.status_code == 422


class TestListEntryRefs:
    async def test_list_refs_empty(self, client: httpx.AsyncClient) -> None:
        resp = await client.get("/v1/entry-refs")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_list_refs_by_from_entry(self, two_entries: TwoEntriesFixture) -> None:
        client, entry_a, entry_b, token = two_entries
        headers = auth_header(token)
        await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a, "to_entry_id": entry_b, "rel": "supports",
        }, headers=headers)

        resp = await client.get("/v1/entry-refs", params={"from_entry_id": entry_a})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["from_entry_id"] == entry_a
        assert data["total"] == 1

    async def test_list_refs_by_rel(self, two_entries: TwoEntriesFixture) -> None:
        client, entry_a, entry_b, token = two_entries
        headers = auth_header(token)
        await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a, "to_entry_id": entry_b, "rel": "contradicts",
        }, headers=headers)

        resp = await client.get("/v1/entry-refs", params={"rel": "contradicts"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 1


class TestGetEntryRef:
    async def test_get_ref(self, two_entries: TwoEntriesFixture) -> None:
        client, entry_a, entry_b, token = two_entries
        create_resp = await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a, "to_entry_id": entry_b, "rel": "generalizes",
        }, headers=auth_header(token))
        ref_id = create_resp.json()["id"]

        resp = await client.get(f"/v1/entry-refs/{ref_id}")
        assert resp.status_code == 200
        assert resp.json()["rel"] == "generalizes"

    async def test_get_ref_not_found(self, client: httpx.AsyncClient) -> None:
        resp = await client.get(f"/v1/entry-refs/{uuid4()}")
        assert resp.status_code == 404


class TestEntryReferences:
    async def test_get_entry_references(self, two_entries: TwoEntriesFixture) -> None:
        client, entry_a, entry_b, token = two_entries
        headers = auth_header(token)
        await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a, "to_entry_id": entry_b, "rel": "supports",
        }, headers=headers)

        resp = await client.get(f"/v1/entries/{entry_a}/references")
        assert resp.status_code == 200
        refs = resp.json()
        assert len(refs) == 1
        assert refs[0]["rel"] == "supports"

    async def test_get_entry_references_direction(self, two_entries: TwoEntriesFixture) -> None:
        client, entry_a, entry_b, token = two_entries
        headers = auth_header(token)
        await client.post("/v1/entry-refs", json={
            "from_entry_id": entry_a, "to_entry_id": entry_b, "rel": "supports",
        }, headers=headers)

        # entry_b has incoming ref
        resp = await client.get(
            f"/v1/entries/{entry_b}/references", params={"direction": "incoming"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # entry_b has no outgoing ref
        resp = await client.get(
            f"/v1/entries/{entry_b}/references", params={"direction": "outgoing"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 0
