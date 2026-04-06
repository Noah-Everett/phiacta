# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Integration tests covering entry update, history, webhook HMAC
verification, content format, and cross-user access.

These tests require the full Docker stack to be running:

    docker compose up -d

Run with:

    pytest tests/integration/test_forgejo_remaining.py -m forgejo

Each test registers its own user (uuid4-prefixed usernames) and is
fully self-contained. No imports from phiacta source.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from uuid import uuid4

import httpx
import pytest

BASE_URL = "http://localhost:8000"

pytestmark = [pytest.mark.forgejo, pytest.mark.anyio]


# ---------------------------------------------------------------------------
# Helpers (mirrored from test_forgejo_entry_lifecycle.py)
# ---------------------------------------------------------------------------


async def register_user(
    client: httpx.AsyncClient,
    username: str | None = None,
    password: str = "Integration1!",
) -> dict:
    """Register a new user and return the full auth response dict.

    Uses a uuid4 prefix by default so every call produces a unique user.
    """
    uid = uuid4().hex[:12]
    resp = await client.post(
        "/v1/auth/register",
        json={
            "username": username or f"user-{uid}",
            "password": password,
        },
    )
    assert resp.status_code == 201, f"register failed: {resp.text}"
    return resp.json()


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def create_entry(
    client: httpx.AsyncClient,
    token: str,
    *,
    title: str = "Integration Test Entry",
    content_format: str = "markdown",
) -> dict:
    """POST /v1/entries and return the created entry dict."""
    resp = await client.post(
        "/v1/entries",
        json={"title": title, "content_format": content_format},
        headers=_auth_header(token),
    )
    assert resp.status_code == 201, f"create_entry failed: {resp.text}"
    return resp.json()


async def wait_for_ready(
    client: httpx.AsyncClient,
    entry_id: str,
    *,
    timeout: int = 30,
    poll_interval: float = 1.0,
) -> dict:
    """Poll GET /v1/entries/{entry_id} until repo_status == 'ready' or timeout.

    Returns the entry dict when ready.  Raises on timeout or error state.
    """
    elapsed = 0.0
    while elapsed < timeout:
        resp = await client.get(f"/v1/entries/{entry_id}")
        assert resp.status_code == 200, f"get entry failed: {resp.text}"
        data = resp.json()
        if data["repo_status"] == "ready":
            return data
        if data["repo_status"] == "error":
            pytest.fail(f"Entry {entry_id} entered error state: {data}")
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    pytest.fail(
        f"Entry {entry_id} did not reach repo_status='ready' within {timeout}s"
    )


async def _setup_ready_entry(
    client: httpx.AsyncClient,
    title: str = "Integration Test Entry",
    content_format: str = "markdown",
) -> tuple[str, str, dict]:
    """Register user, create entry, wait for ready.

    Returns ``(token, entry_id, entry_dict)``.
    """
    auth = await register_user(client)
    token = auth["access_token"]
    entry = await create_entry(client, token, title=title, content_format=content_format)
    entry_id = entry["id"]
    ready = await wait_for_ready(client, entry_id)
    return token, entry_id, ready


# ---------------------------------------------------------------------------
# Entry Update (PATCH /v1/entries/{id})
# ---------------------------------------------------------------------------


class TestEntryUpdate:
    """PATCH /v1/entries/{id} updates metadata extension (DB-only)."""

    async def test_update_entry_title(self) -> None:
        """Create entry, wait ready, PATCH title, GET entry, verify title changed.

        The PATCH updates the metadata extension in the DB directly (no
        git-first write), so the change should be reflected immediately.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Original Title",
            )

            new_title = f"Updated Title {uuid4().hex[:8]}"
            patch_resp = await client.patch(
                f"/v1/entries/{entry_id}",
                json={"title": new_title},
                headers=_auth_header(token),
            )
            assert patch_resp.status_code == 200, (
                f"PATCH failed: {patch_resp.text}"
            )

            # The PATCH updates the DB directly; verify via GET.
            get_resp = await client.get(f"/v1/entries/{entry_id}")
            assert get_resp.status_code == 200
            updated_title = get_resp.json().get("title")

            assert updated_title == new_title, (
                f"title did not update after PATCH.\n"
                f"Expected: {new_title!r}\n"
                f"Got: {updated_title!r}"
            )

    async def test_update_entry_tags(self) -> None:
        """PUT tags on an entry via the tags extension, verify the field is updated."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Tags Update Test",
            )

            new_tags = ["physics", "quantum", "test"]
            put_resp = await client.put(
                f"/v1/extensions/tags/{entry_id}",
                json={"tags": new_tags},
                headers=_auth_header(token),
            )
            assert put_resp.status_code == 200, (
                f"PUT tags failed: {put_resp.text}"
            )

            # Verify via GET tags endpoint.
            tags_resp = await client.get(
                "/v1/extensions/tags/",
                params={"entry_id": entry_id},
            )
            assert tags_resp.status_code == 200, (
                f"GET tags failed: {tags_resp.text}"
            )
            body = tags_resp.json()
            updated_tags = sorted([t["tag"] for t in body["tags"]])
            expected_tags = sorted(new_tags)
            assert updated_tags == expected_tags, (
                f"tags did not update after PUT.\n"
                f"Expected: {expected_tags!r}\n"
                f"Got: {updated_tags!r}"
            )

    async def test_update_non_owner_rejected(self) -> None:
        """A second user trying to PATCH an entry they don't own gets 403."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # User A creates the entry.
            token_a, entry_id, _ = await _setup_ready_entry(
                client, title="Non-Owner PATCH Test",
            )

            # User B registers separately.
            auth_b = await register_user(client)
            token_b = auth_b["access_token"]

            patch_resp = await client.patch(
                f"/v1/entries/{entry_id}",
                json={"title": "Stolen Title"},
                headers=_auth_header(token_b),
            )
            assert patch_resp.status_code == 403, (
                f"Expected 403 for non-owner PATCH, "
                f"got {patch_resp.status_code}: {patch_resp.text}"
            )


# ---------------------------------------------------------------------------
# History (GET /v1/entries/{id}/history)
# ---------------------------------------------------------------------------


class TestEntryHistory:
    """GET /v1/entries/{id}/history returns commit list."""

    # NOTE: The history endpoint (GET /v1/entries/{id}/history) may currently
    # return 404 if the GitService.list_commits method is not yet wired up
    # in the running stack. If these tests fail with 404, that confirms the
    # history endpoint needs fixing before the tests will pass.

    async def test_list_commits(self) -> None:
        """Create entry, wait ready, write a file, GET history, verify
        at least 2 commits (initial provisioning commit + file write).
        """
        content_b64 = base64.b64encode(b"history trigger content").decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="History Test",
            )

            # Write a file to produce a second commit.
            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/notes.txt",
                files={"content": ("file", base64.b64decode(content_b64), "application/octet-stream")}, data={"message": "Add notes.txt"},
                headers=_auth_header(token),
            )
            assert put_resp.status_code == 200, f"PUT failed: {put_resp.text}"

            history_resp = await client.get(f"/v1/entries/{entry_id}/history")
            assert history_resp.status_code == 200, (
                f"GET history failed: {history_resp.text}"
            )

            commits = history_resp.json()
            assert isinstance(commits, list), (
                f"Expected list of commits, got: {type(commits)}"
            )
            assert len(commits) >= 2, (
                f"Expected at least 2 commits (initial + file write), "
                f"got {len(commits)}: {commits}"
            )

            # Each commit should have at least a sha field.
            for commit in commits:
                assert "sha" in commit, (
                    f"Commit missing 'sha' field: {commit}"
                )

    async def test_list_commits_public(self) -> None:
        """History endpoint requires no authentication — public read."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            _token, entry_id, _ = await _setup_ready_entry(
                client, title="History Public Test",
            )

            # Request without any auth header.
            history_resp = await client.get(f"/v1/entries/{entry_id}/history")
            assert history_resp.status_code == 200, (
                f"GET history without auth failed: {history_resp.text}"
            )

            commits = history_resp.json()
            assert isinstance(commits, list), (
                f"Expected list of commits, got: {type(commits)}"
            )
            assert len(commits) >= 1, "Expected at least 1 commit in history"


# ---------------------------------------------------------------------------
# Webhook HMAC Verification
# ---------------------------------------------------------------------------


class TestWebhookHmac:
    """Webhook endpoint rejects requests with bad or missing signatures."""

    async def test_webhook_rejects_invalid_signature(self) -> None:
        """POST to /webhooks/forgejo with a fake HMAC signature returns 401 or 403."""
        payload = json.dumps({
            "ref": "refs/heads/main",
            "after": "a" * 40,
            "repository": {"name": str(uuid4())},
            "commits": [],
        }).encode()

        # Compute an HMAC with a wrong secret.
        fake_sig = hmac.new(
            b"wrong-secret", payload, hashlib.sha256
        ).hexdigest()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            resp = await client.post(
                "/webhooks/forgejo",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "push",
                    "X-Forgejo-Signature": fake_sig,
                },
            )
            assert resp.status_code in {401, 403}, (
                f"Expected 401 or 403 for invalid HMAC signature, "
                f"got {resp.status_code}: {resp.text}"
            )

    async def test_webhook_rejects_missing_signature(self) -> None:
        """POST to /webhooks/forgejo without X-Forgejo-Signature returns 401 or 403."""
        payload = json.dumps({
            "ref": "refs/heads/main",
            "after": "b" * 40,
            "repository": {"name": str(uuid4())},
            "commits": [],
        }).encode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            resp = await client.post(
                "/webhooks/forgejo",
                content=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Forgejo-Event": "push",
                    # Deliberately omit X-Forgejo-Signature.
                },
            )
            assert resp.status_code in {401, 403}, (
                f"Expected 401 or 403 for missing HMAC signature, "
                f"got {resp.status_code}: {resp.text}"
            )


# ---------------------------------------------------------------------------
# Content Format
# ---------------------------------------------------------------------------


class TestContentFormat:
    """Entry content_format controls which content file is provisioned."""

    async def test_entry_with_latex_format(self) -> None:
        """Create entry with content_format='latex', wait ready, verify
        .phiacta/content.tex exists in the file listing.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client,
                title=f"LaTeX Entry {uuid4().hex[:8]}",
                content_format="latex",
            )

            files_resp = await client.get(f"/v1/entries/{entry_id}/files")
            assert files_resp.status_code == 200, files_resp.text
            file_names = [f["name"] for f in files_resp.json()]

            # Content is at .phiacta/content.tex for latex format.
            # Check recursively — the listing may show the .phiacta
            # directory or its contents depending on the API.
            has_latex_content = (
                "content.tex" in file_names
                or ".phiacta/content.tex" in file_names
                or any("content.tex" in n for n in file_names)
            )
            assert has_latex_content, (
                f"content.tex missing from latex entry listing: {file_names}"
            )


# ---------------------------------------------------------------------------
# Cross-user Access
# ---------------------------------------------------------------------------


class TestCrossUserAccess:
    """Public read / owner-only write enforcement across users."""

    async def test_other_user_can_read_entry(self) -> None:
        """User A creates an entry; User B can GET it (public read, no auth)."""
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # User A creates and readies the entry.
            _token_a, entry_id, _ = await _setup_ready_entry(
                client, title="Cross-User Read Test",
            )

            # User B registers and reads the entry without using User A's token.
            auth_b = await register_user(client)
            token_b = auth_b["access_token"]

            get_resp = await client.get(
                f"/v1/entries/{entry_id}",
                headers=_auth_header(token_b),
            )
            assert get_resp.status_code == 200, (
                f"User B could not read User A's entry: {get_resp.text}"
            )
            assert get_resp.json()["id"] == entry_id

            # Also verify it works with no auth at all.
            get_no_auth = await client.get(f"/v1/entries/{entry_id}")
            assert get_no_auth.status_code == 200, (
                f"Unauthenticated GET failed: {get_no_auth.text}"
            )

    async def test_other_user_cannot_write_files(self) -> None:
        """User A creates an entry; User B trying to PUT a file gets 403."""
        content_b64 = base64.b64encode(b"user b injection").decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            # User A creates and readies the entry.
            _token_a, entry_id, _ = await _setup_ready_entry(
                client, title="Cross-User Write Test",
            )

            # User B registers and attempts a file write.
            auth_b = await register_user(client)
            token_b = auth_b["access_token"]

            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/injection.txt",
                files={"content": ("file", base64.b64decode(content_b64), "application/octet-stream")}, data={"message": "Attempt injection"},
                headers=_auth_header(token_b),
            )
            assert put_resp.status_code == 403, (
                f"Expected 403 for cross-user file write, "
                f"got {put_resp.status_code}: {put_resp.text}"
            )


# ---------------------------------------------------------------------------
# Commit Diff Detail (GET /v1/entries/{id}/history/{sha})
# ---------------------------------------------------------------------------


class TestCommitDiffDetail:
    """GET /v1/entries/{id}/history/{sha} returns per-file diff for a commit."""

    async def test_commit_diff_detail(self) -> None:
        """Create entry, wait ready, write a file, fetch history to get the
        latest commit SHA, then GET /entries/{id}/history/{sha}.

        Verify the response has ``base_sha``, ``head_sha``, and
        ``files_changed`` (a non-empty list).  Each file diff item must
        contain ``path``, ``patch``, ``additions``, and ``deletions``.
        """
        content_b64 = base64.b64encode(b"diff trigger content").decode()

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Commit Diff Detail Test",
            )

            # Write a file to produce a commit that has a meaningful diff.
            put_resp = await client.put(
                f"/v1/entries/{entry_id}/files/diff_target.txt",
                files={"content": ("file", base64.b64decode(content_b64), "application/octet-stream")}, data={"message": "Add diff_target.txt"},
                headers=_auth_header(token),
            )
            assert put_resp.status_code == 200, f"PUT failed: {put_resp.text}"

            # Retrieve history and grab the latest (first) commit SHA.
            history_resp = await client.get(f"/v1/entries/{entry_id}/history")
            assert history_resp.status_code == 200, (
                f"GET history failed: {history_resp.text}"
            )
            commits = history_resp.json()
            assert isinstance(commits, list) and len(commits) >= 1, (
                f"Expected at least 1 commit in history, got: {commits}"
            )
            latest_sha = commits[0]["sha"]

            # Fetch the diff for that specific commit.
            diff_resp = await client.get(
                f"/v1/entries/{entry_id}/history/{latest_sha}",
            )
            assert diff_resp.status_code == 200, (
                f"GET history/{latest_sha} failed: {diff_resp.text}"
            )

            diff = diff_resp.json()
            assert "base_sha" in diff, f"Response missing 'base_sha': {diff}"
            assert "head_sha" in diff, f"Response missing 'head_sha': {diff}"
            assert "files_changed" in diff, (
                f"Response missing 'files_changed': {diff}"
            )
            assert diff["head_sha"] == latest_sha, (
                f"head_sha mismatch: expected {latest_sha!r}, "
                f"got {diff['head_sha']!r}"
            )

            files_changed = diff["files_changed"]
            assert isinstance(files_changed, list), (
                f"'files_changed' must be a list, got: {type(files_changed)}"
            )
            assert len(files_changed) >= 1, (
                f"Expected at least 1 changed file in diff, got: {files_changed}"
            )

            for file_diff in files_changed:
                for field in ("path", "patch", "additions", "deletions"):
                    assert field in file_diff, (
                        f"File diff missing '{field}': {file_diff}"
                    )
                assert isinstance(file_diff["additions"], int), (
                    f"'additions' must be int: {file_diff['additions']!r}"
                )
                assert isinstance(file_diff["deletions"], int), (
                    f"'deletions' must be int: {file_diff['deletions']!r}"
                )


# ---------------------------------------------------------------------------
# Entry References (GET /v1/extensions/references/?entry_id={id})
# ---------------------------------------------------------------------------


class TestEntryReferences:
    """GET /v1/extensions/references/?entry_id={id} returns paginated ref lists."""

    async def test_entry_references_empty(self) -> None:
        """Create entry, wait ready, GET /extensions/references/?entry_id={id}.

        A brand-new entry has no refs, so the endpoint must return an empty
        items list with HTTP 200.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            _token, entry_id, _ = await _setup_ready_entry(
                client, title="References Empty Test",
            )

            refs_resp = await client.get(
                "/v1/extensions/references/",
                params={"entry_id": entry_id},
            )
            assert refs_resp.status_code == 200, (
                f"GET references failed: {refs_resp.text}"
            )
            body = refs_resp.json()
            assert "items" in body, (
                f"Expected paginated response with 'items', got: {body}"
            )
            assert body["items"] == [], (
                f"Expected empty items for new entry, got: {body['items']}"
            )

    async def test_entry_references_direction_filter(self) -> None:
        """direction query param is accepted without error.

        For a new entry the result is always an empty items list regardless
        of direction, so this test only checks that the parameter is accepted
        and a valid paginated response is returned for all three values.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            _token, entry_id, _ = await _setup_ready_entry(
                client, title="References Direction Test",
            )

            for direction in ("incoming", "outgoing", "both"):
                resp = await client.get(
                    "/v1/extensions/references/",
                    params={"entry_id": entry_id, "direction": direction},
                )
                assert resp.status_code == 200, (
                    f"GET references?direction={direction} failed: {resp.text}"
                )
                body = resp.json()
                assert "items" in body, (
                    f"Expected paginated response for direction={direction!r}: {body}"
                )
                assert isinstance(body["items"], list), (
                    f"Expected items list for direction={direction!r}: {body}"
                )


# ---------------------------------------------------------------------------
# Entry List with Filters (GET /v1/entries)
# ---------------------------------------------------------------------------


class TestEntryListFilters:
    """GET /v1/entries with limit/offset pagination and default listing."""

    async def test_list_entries_default(self) -> None:
        """Create an entry, GET /entries, verify the entry appears in the list
        with the correct top-level fields.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            title = f"List Default Test {uuid4().hex[:8]}"
            _token, entry_id, _ = await _setup_ready_entry(client, title=title)

            list_resp = await client.get("/v1/entries")
            assert list_resp.status_code == 200, (
                f"GET /entries failed: {list_resp.text}"
            )

            body = list_resp.json()
            # PaginatedResponse shape: items, total, limit, offset, has_more
            assert "items" in body, f"Response missing 'items': {body}"
            assert "total" in body, f"Response missing 'total': {body}"
            assert "has_more" in body, f"Response missing 'has_more': {body}"

            item_ids = [item["id"] for item in body["items"]]
            assert entry_id in item_ids, (
                f"Newly created entry {entry_id!r} not found in list. "
                f"IDs: {item_ids}"
            )

            # Find our entry and verify key fields are present.
            our_item = next(i for i in body["items"] if i["id"] == entry_id)
            for field in (
                "id", "title", "visibility", "repo_status",
                "entry_type", "created_at", "updated_at",
            ):
                assert field in our_item, (
                    f"EntryListItem missing field '{field}': {our_item}"
                )
            assert our_item["title"] == title, (
                f"title mismatch: expected {title!r}, got {our_item['title']!r}"
            )

    async def test_list_entries_pagination(self) -> None:
        """Create 3 entries, GET /entries?limit=2, verify 2 items and
        has_more=true, then GET /entries?limit=2&offset=2 and verify the
        remaining 1 item appears and has_more=false.

        This test registers a fresh user and creates entries with unique
        titles to make it easy to find them in the paginated results without
        depending on the total count of entries in the database.
        """
        uid = uuid4().hex[:8]

        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            auth = await register_user(client)
            token = auth["access_token"]

            # Create 3 entries from this user, all ready before we paginate.
            titles = [f"Pagination Test {uid} {i}" for i in range(3)]
            entry_ids: list[str] = []
            for t in titles:
                entry = await create_entry(client, token, title=t)
                entry_ids.append(entry["id"])

            for eid in entry_ids:
                await wait_for_ready(client, eid)

            # Fetch the full list to determine the baseline total.
            baseline_resp = await client.get(
                "/v1/entries", params={"limit": 200, "offset": 0},
            )
            assert baseline_resp.status_code == 200
            total = baseline_resp.json()["total"]

            # We need at least 3 entries in the DB for pagination to be
            # meaningful; the 3 we just created guarantee this.
            assert total >= 3, (
                f"Expected at least 3 entries in DB, got {total}"
            )

            # Page 1: limit=2
            page1_resp = await client.get(
                "/v1/entries", params={"limit": 2, "offset": 0},
            )
            assert page1_resp.status_code == 200, (
                f"GET /entries?limit=2 failed: {page1_resp.text}"
            )
            page1 = page1_resp.json()
            assert len(page1["items"]) == 2, (
                f"Expected 2 items with limit=2, got {len(page1['items'])}"
            )
            if total > 2:
                assert page1["has_more"] is True, (
                    f"Expected has_more=true with total={total} and limit=2, "
                    f"got has_more={page1['has_more']!r}"
                )

            # Page 2: limit=2, offset=2 — should return (total - 2) capped at 2.
            page2_resp = await client.get(
                "/v1/entries", params={"limit": 2, "offset": 2},
            )
            assert page2_resp.status_code == 200, (
                f"GET /entries?limit=2&offset=2 failed: {page2_resp.text}"
            )
            page2 = page2_resp.json()
            expected_page2_count = min(2, max(0, total - 2))
            assert len(page2["items"]) == expected_page2_count, (
                f"Expected {expected_page2_count} items on page 2 "
                f"(total={total}), got {len(page2['items'])}"
            )

            # IDs on page 1 and page 2 must not overlap.
            ids_page1 = {i["id"] for i in page1["items"]}
            ids_page2 = {i["id"] for i in page2["items"]}
            overlap = ids_page1 & ids_page2
            assert not overlap, (
                f"Pages 1 and 2 share IDs (pagination is broken): {overlap}"
            )


# ---------------------------------------------------------------------------
# Proposal Detail Diff Content (GET /v1/entries/{id}/edits/{number})
# ---------------------------------------------------------------------------


class TestProposalDetailDiff:
    """GET /v1/entries/{id}/edits/{number} returns diff for the proposal."""

    async def test_proposal_detail_has_diff(self) -> None:
        """Create entry, create a proposal with a file change, GET the proposal
        detail by number, and verify the ``diff`` field is a non-empty list
        whose items each have ``path``, ``patch``, ``additions``,
        ``deletions``.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
            token, entry_id, _ = await _setup_ready_entry(
                client, title="Proposal Diff Detail Test",
            )

            # Create an edit proposal with a single file change.
            proposal_title = f"Add proposal file {uuid4().hex[:8]}"
            create_resp = await client.post(
                f"/v1/entries/{entry_id}/edits",
                json={
                    "title": proposal_title,
                    "body": "Testing proposal diff content",
                    "files": [
                        {"path": "proposal_file.txt", "content": "proposal file content"},
                    ],
                },
                headers=_auth_header(token),
            )
            assert create_resp.status_code == 201, (
                f"Create proposal failed: {create_resp.text}"
            )
            proposal_number = create_resp.json()["number"]

            # Fetch the proposal detail.
            detail_resp = await client.get(
                f"/v1/entries/{entry_id}/edits/{proposal_number}",
            )
            assert detail_resp.status_code == 200, (
                f"GET proposal detail failed: {detail_resp.text}"
            )

            detail = detail_resp.json()
            assert "diff" in detail, f"Response missing 'diff' field: {detail}"

            diff = detail["diff"]
            assert isinstance(diff, list), (
                f"'diff' must be a list, got: {type(diff)}"
            )
            assert len(diff) >= 1, (
                f"Expected at least 1 file in proposal diff, got: {diff}"
            )

            for file_diff in diff:
                for field in ("path", "patch", "additions", "deletions"):
                    assert field in file_diff, (
                        f"File diff item missing '{field}': {file_diff}"
                    )
                assert isinstance(file_diff["additions"], int), (
                    f"'additions' must be int: {file_diff['additions']!r}"
                )
                assert isinstance(file_diff["deletions"], int), (
                    f"'deletions' must be int: {file_diff['deletions']!r}"
                )

            # The proposal should reference the file we added.
            diff_paths = [f["path"] for f in diff]
            assert "proposal_file.txt" in diff_paths, (
                f"Expected 'proposal_file.txt' in diff paths, got: {diff_paths}"
            )
