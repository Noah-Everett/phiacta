# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for webhook ingestion endpoint (NEV-118).

Tests the POST /webhooks/forgejo endpoint for:
- HMAC signature verification
- Event type filtering (only push events)
- Branch filtering (only main branch)
- Edge cases (deletion pushes, unknown repos)

Since E2E tests run against SQLite without Forgejo, we test request
validation and basic handling. The git_service calls that would fetch
file contents from Forgejo are not exercised here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.models.entry import Entry
from tests.e2e.conftest import TEST_WEBHOOK_SECRET, auth_header, register_agent


def _compute_forgejo_signature(body: bytes, secret: str) -> str:
    """Compute HMAC-SHA256 signature matching Forgejo's format."""
    mac = hmac.new(secret.encode(), body, hashlib.sha256)
    return mac.hexdigest()


def _make_push_payload(
    *,
    repo_name: str = "test-repo",
    ref: str = "refs/heads/main",
    after: str = "abc123def456",
    before: str = "000000000000",
) -> dict:
    """Construct a minimal Forgejo push webhook payload."""
    return {
        "ref": ref,
        "before": before,
        "after": after,
        "repository": {
            "name": repo_name,
            "full_name": f"phiacta/{repo_name}",
            "id": 42,
        },
        "commits": [
            {
                "id": after,
                "message": "Update entry.yaml",
            }
        ],
        "sender": {
            "login": "test-user",
        },
    }


async def _create_entry_for_webhook(
    client: httpx.AsyncClient,
) -> tuple[str, str, str]:
    """Register an agent, create an entry, return (entry_id, repo_name, token)."""
    uid = uuid4().hex[:8]
    auth = await register_agent(
        client, handle=f"wh-{uid}", email=f"wh-{uid}@example.com"
    )
    token = auth["access_token"]
    resp = await client.post(
        "/v1/entries",
        json={"title": "Webhook Target Entry"},
        headers=auth_header(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["id"], data["repo_name"], token


class TestWebhookSignatureVerification:
    """Scenario: Webhook endpoint rejects requests without valid HMAC signatures."""

    async def test_webhook_rejects_missing_signature(
        self, client: httpx.AsyncClient
    ) -> None:
        """POST without X-Forgejo-Signature header returns 401 or 403."""
        payload = _make_push_payload()
        resp = await client.post(
            "/webhooks/forgejo",
            json=payload,
            headers={"X-Forgejo-Event": "push"},
        )
        # Missing signature should be unauthorized
        assert resp.status_code in (401, 403)

    async def test_webhook_rejects_invalid_signature(
        self, client: httpx.AsyncClient
    ) -> None:
        """POST with wrong HMAC signature returns 401 or 403."""
        payload = _make_push_payload()
        body = json.dumps(payload).encode()
        wrong_sig = _compute_forgejo_signature(body, "wrong-secret-entirely")
        resp = await client.post(
            "/webhooks/forgejo",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "push",
                "X-Forgejo-Signature": wrong_sig,
            },
        )
        assert resp.status_code in (401, 403)

    async def test_webhook_rejects_tampered_body(
        self, client: httpx.AsyncClient
    ) -> None:
        """Signature computed on different body than what's sent is rejected."""
        payload = _make_push_payload()
        # Sign the original payload
        original_body = json.dumps(payload).encode()
        sig = _compute_forgejo_signature(original_body, TEST_WEBHOOK_SECRET)

        # Send a different payload with the original signature
        tampered_payload = _make_push_payload(after="tampered_sha_value")
        tampered_body = json.dumps(tampered_payload).encode()
        resp = await client.post(
            "/webhooks/forgejo",
            content=tampered_body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "push",
                "X-Forgejo-Signature": sig,
            },
        )
        assert resp.status_code in (401, 403)


class TestWebhookEventFiltering:
    """Scenario: Webhook only processes push events to the main branch."""

    async def test_webhook_ignores_non_push_events(
        self, client: httpx.AsyncClient
    ) -> None:
        """POST with X-Forgejo-Event other than push returns 200, no processing."""
        payload = _make_push_payload()
        body = json.dumps(payload).encode()
        sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
        resp = await client.post(
            "/webhooks/forgejo",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "issues",
                "X-Forgejo-Signature": sig,
            },
        )
        # Non-push events are acknowledged but ignored
        assert resp.status_code == 200

    async def test_webhook_ignores_non_main_branch(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Push to refs/heads/feature-branch returns 200 without updating entry."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)

        payload = _make_push_payload(
            repo_name=repo_name,
            ref="refs/heads/feature-branch",
            after="feature_sha_123",
        )
        body = json.dumps(payload).encode()
        sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
        resp = await client.post(
            "/webhooks/forgejo",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "push",
                "X-Forgejo-Signature": sig,
            },
        )
        assert resp.status_code == 200

        # Entry should NOT have its head SHA updated
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.current_head_sha != "feature_sha_123"

    async def test_webhook_ignores_branch_deletion(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Push with after=0000...0000 (branch deletion) returns 200, no update."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        zero_sha = "0" * 40

        payload = _make_push_payload(
            repo_name=repo_name,
            ref="refs/heads/main",
            after=zero_sha,
        )
        body = json.dumps(payload).encode()
        sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
        resp = await client.post(
            "/webhooks/forgejo",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "push",
                "X-Forgejo-Signature": sig,
            },
        )
        assert resp.status_code == 200

        # Entry should NOT have zero SHA as head
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.current_head_sha != zero_sha


class TestWebhookUnknownRepo:
    """Scenario: Webhook receives push for a repo not tracked in our database."""

    async def test_webhook_ignores_unknown_repo(
        self, client: httpx.AsyncClient
    ) -> None:
        """Push for repo with a name that is not a valid entry UUID returns 200."""
        payload = _make_push_payload(repo_name="not-a-uuid-repo-name")
        body = json.dumps(payload).encode()
        sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
        resp = await client.post(
            "/webhooks/forgejo",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "push",
                "X-Forgejo-Signature": sig,
            },
        )
        # Should not crash -- returns 200
        assert resp.status_code == 200

    async def test_webhook_ignores_valid_uuid_not_in_db(
        self, client: httpx.AsyncClient
    ) -> None:
        """Push for repo with valid UUID name but no matching entry returns 200."""
        fake_entry_id = str(uuid4())
        payload = _make_push_payload(
            repo_name=fake_entry_id,
            ref="refs/heads/main",
            after="abc123" * 6 + "abcd",
        )
        body = json.dumps(payload).encode()
        sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
        resp = await client.post(
            "/webhooks/forgejo",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "push",
                "X-Forgejo-Signature": sig,
            },
        )
        # Should not crash
        assert resp.status_code == 200


class TestWebhookPushHappyPath:
    """Scenario: Valid push webhook updates entry head SHA."""

    async def test_webhook_updates_head_sha_on_valid_push(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Push to main branch with valid signature updates current_head_sha."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)

        new_sha = "a" * 40  # valid 40-char hex SHA
        payload = _make_push_payload(
            repo_name=repo_name,
            ref="refs/heads/main",
            after=new_sha,
        )
        body = json.dumps(payload).encode()
        sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
        resp = await client.post(
            "/webhooks/forgejo",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "push",
                "X-Forgejo-Signature": sig,
            },
        )
        assert resp.status_code == 200

        # Verify the entry's head SHA was updated
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.current_head_sha == new_sha

    async def test_webhook_rejects_invalid_sha_format(
        self,
        client: httpx.AsyncClient,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Push with non-hex or wrong-length SHA is silently ignored."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)

        payload = _make_push_payload(
            repo_name=repo_name,
            ref="refs/heads/main",
            after="not-a-valid-sha-at-all",
        )
        body = json.dumps(payload).encode()
        sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
        resp = await client.post(
            "/webhooks/forgejo",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Forgejo-Event": "push",
                "X-Forgejo-Signature": sig,
            },
        )
        assert resp.status_code == 200

        # Entry's head SHA should NOT have been updated
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.current_head_sha != "not-a-valid-sha-at-all"
