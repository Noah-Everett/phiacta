# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""E2E tests for webhook ingestion endpoint (NEV-118, NEV-119).

Tests the POST /webhooks/forgejo endpoint for:
- HMAC signature verification (NEV-118)
- Event type filtering (only push events) (NEV-118)
- Branch filtering (only main branch) (NEV-118)
- Edge cases (deletion pushes, unknown repos) (NEV-118)
- Push ingestion: entry.yaml -> entry metadata sync (NEV-119)
- Push ingestion: README -> content_cache sync (NEV-119)
- Push ingestion: refs.yaml -> entry_refs sync (NEV-119)
- Error handling for malformed / missing files (NEV-119)
"""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID, uuid4

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from phiacta.models.entry import Entry
from phiacta.models.entry_ref import EntryRef
from tests.e2e.conftest import (
    TEST_WEBHOOK_SECRET,
    FakeGitService,
    auth_header,
    register_agent,
)


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


# ---------------------------------------------------------------------------
# Helpers for NEV-119 ingestion tests
# ---------------------------------------------------------------------------


def _build_entry_yaml(
    entry_id: str,
    *,
    title: str = "Ingested Entry Title",
    content_format: str = "markdown",
    tags: list[str] | None = None,
    summary: str | None = None,
    license_: str | None = None,
    layout_hint: str | None = None,
    schema_version: int = 1,
) -> str:
    """Build a valid .phiacta/entry.yaml string for testing."""
    data: dict = {
        "entry_id": f"ent_{entry_id}",
        "schema_version": schema_version,
        "title": title,
        "content_format": content_format,
        "author": {"id": f"usr_{uuid4()}", "name": "test-author"},
        "created_at": "2026-03-15T12:00:00+00:00",
    }
    if tags is not None:
        data["tags"] = tags
    if summary is not None:
        data["summary"] = summary
    if license_ is not None:
        data["license"] = license_
    if layout_hint is not None:
        data["layout_hint"] = layout_hint
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _build_refs_yaml(refs: list[dict]) -> str:
    """Build a valid .phiacta/refs.yaml string for testing."""
    return yaml.dump({"refs": refs}, default_flow_style=False, sort_keys=False)


def _populate_fake_git(
    fake_git: FakeGitService,
    entry_id: str,
    *,
    entry_yaml: str | None = None,
    readme_content: str | None = None,
    readme_ext: str = ".md",
    refs_yaml: str | None = None,
) -> None:
    """Populate the FakeGitService with files for an entry.

    Clears all existing files for the entry first, then sets only the files
    that are explicitly passed. This ensures that not passing a file (e.g.
    refs_yaml=None) means the file is absent from the repo.
    """
    eid = UUID(entry_id)
    # Clear all files for this entry so omitted files are truly absent
    fake_git.files = {k: v for k, v in fake_git.files.items() if k[0] != eid}
    if entry_yaml is not None:
        fake_git.files[(eid, ".phiacta/entry.yaml")] = entry_yaml.encode("utf-8")
    if readme_content is not None:
        fake_git.files[(eid, f"README{readme_ext}")] = readme_content.encode("utf-8")
    if refs_yaml is not None:
        fake_git.files[(eid, ".phiacta/refs.yaml")] = refs_yaml.encode("utf-8")


def _send_push(
    client: httpx.AsyncClient,
    repo_name: str,
    after_sha: str = "a" * 40,
) -> tuple[bytes, dict]:
    """Build the push webhook request body and headers."""
    payload = _make_push_payload(
        repo_name=repo_name,
        ref="refs/heads/main",
        after=after_sha,
    )
    body = json.dumps(payload).encode()
    sig = _compute_forgejo_signature(body, TEST_WEBHOOK_SECRET)
    headers = {
        "Content-Type": "application/json",
        "X-Forgejo-Event": "push",
        "X-Forgejo-Signature": sig,
    }
    return body, headers


async def _create_two_entries_for_refs(
    client: httpx.AsyncClient,
) -> tuple[str, str, str, str]:
    """Create two entries for ref testing. Returns (entry_a_id, repo_a, entry_b_id, repo_b)."""
    entry_a_id, repo_a, _ = await _create_entry_for_webhook(client)
    entry_b_id, repo_b, _ = await _create_entry_for_webhook(client)
    return entry_a_id, repo_a, entry_b_id, repo_b


# ---------------------------------------------------------------------------
# NEV-119: Push Ingestion -- entry.yaml -> entry metadata
# ---------------------------------------------------------------------------


class TestIngestionEntryYamlHappyPath:
    """Scenario: Webhook push ingests entry.yaml and updates entry metadata."""

    async def test_ingestion_updates_title_from_entry_yaml(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Push with valid entry.yaml updates the entry title in Postgres."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        entry_yaml = _build_entry_yaml(entry_id, title="Updated Title from YAML")
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.title == "Updated Title from YAML"

    async def test_ingestion_updates_all_metadata_fields(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Push ingests all metadata fields: title, tags, summary, license, layout_hint,
        content_format, schema_version."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        entry_yaml = _build_entry_yaml(
            entry_id,
            title="Comprehensive Quantum Study",
            content_format="latex",
            tags=["quantum", "entanglement", "decoherence"],
            summary="A deep dive into quantum entanglement phenomena.",
            license_="CC-BY-SA-4.0",
            layout_hint="research-paper",
            schema_version=2,
        )
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.title == "Comprehensive Quantum Study"
            assert entry.content_format == "latex"
            assert entry.tags == ["quantum", "entanglement", "decoherence"]
            assert entry.summary == "A deep dive into quantum entanglement phenomena."
            assert entry.license == "CC-BY-SA-4.0"
            assert entry.layout_hint == "research-paper"
            assert entry.schema_version == 2

    async def test_ingestion_updates_content_cache_from_readme(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Push with README.md populates content_cache on the entry."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        readme_text = "# My Research\n\nThis is a study of quantum entanglement.\n"
        entry_yaml = _build_entry_yaml(entry_id, content_format="markdown")
        _populate_fake_git(
            fake_git, entry_id, entry_yaml=entry_yaml, readme_content=readme_text
        )

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.content_cache == readme_text

    async def test_ingestion_reads_readme_tex_for_latex_format(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When content_format is latex, README.tex is fetched for content_cache."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        latex_content = r"\section{Introduction}" + "\nQuantum mechanics...\n"
        entry_yaml = _build_entry_yaml(entry_id, content_format="latex")
        _populate_fake_git(
            fake_git, entry_id,
            entry_yaml=entry_yaml,
            readme_content=latex_content,
            readme_ext=".tex",
        )

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.content_cache == latex_content

    async def test_ingestion_reads_readme_txt_for_plain_format(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """When content_format is plain, README.txt is fetched for content_cache."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        plain_content = "This is plain text content.\nNo formatting.\n"
        entry_yaml = _build_entry_yaml(entry_id, content_format="plain")
        _populate_fake_git(
            fake_git, entry_id,
            entry_yaml=entry_yaml,
            readme_content=plain_content,
            readme_ext=".txt",
        )

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.content_cache == plain_content

    async def test_ingestion_head_sha_updated_on_success(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """After ingestion, current_head_sha reflects the push's after SHA."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        new_sha = "b" * 40
        entry_yaml = _build_entry_yaml(entry_id)
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        body, headers = _send_push(client, repo_name, after_sha=new_sha)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.current_head_sha == new_sha

    async def test_ingestion_unicode_in_yaml_fields(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Unicode content in entry.yaml fields is preserved through ingestion."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        entry_yaml = _build_entry_yaml(
            entry_id,
            title="\u91cf\u5b50\u529b\u5b66\u306e\u57fa\u790e",
            summary="\u6982\u8981: \u91cf\u5b50\u529b\u5b66\u306e\u57fa\u672c\u7684\u306a\u6982\u5ff5",
            tags=["\u7269\u7406\u5b66", "\u91cf\u5b50"],
        )
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.title == "\u91cf\u5b50\u529b\u5b66\u306e\u57fa\u790e"
            assert "\u91cf\u5b50\u529b\u5b66" in entry.summary


class TestIngestionFieldTruncation:
    """Scenario: Overly long field values in entry.yaml are truncated to column max."""

    async def test_title_truncated_to_500_chars(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Title longer than 500 chars in YAML is truncated, not rejected."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        long_title = "A" * 600
        entry_yaml = _build_entry_yaml(entry_id, title=long_title)
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert len(entry.title) <= 500
            assert entry.title == long_title[:500]

    async def test_layout_hint_truncated_to_50_chars(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """layout_hint longer than 50 chars in YAML is truncated."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        long_hint = "x" * 100
        entry_yaml = _build_entry_yaml(entry_id, layout_hint=long_hint)
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert len(entry.layout_hint) <= 50
            assert entry.layout_hint == long_hint[:50]

    async def test_license_truncated_to_50_chars(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """license longer than 50 chars in YAML is truncated."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        long_license = "L" * 80
        entry_yaml = _build_entry_yaml(entry_id, license_=long_license)
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert len(entry.license) <= 50
            assert entry.license == long_license[:50]


class TestIngestionIdempotency:
    """Scenario: Duplicate pushes with the same SHA are idempotent."""

    async def test_idempotent_push_skips_second_ingestion(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """If current_head_sha already equals after_sha, skip ingestion entirely."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        sha = "c" * 40
        entry_yaml = _build_entry_yaml(entry_id, title="First Ingestion")
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        # First push -- ingests normally
        body, headers = _send_push(client, repo_name, after_sha=sha)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        # Verify first ingestion worked
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.title == "First Ingestion"
            assert entry.current_head_sha == sha

        # Update the fake with a different title
        entry_yaml_v2 = _build_entry_yaml(entry_id, title="Should NOT Apply")
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml_v2)

        # Second push with SAME sha -- should be skipped
        body2, headers2 = _send_push(client, repo_name, after_sha=sha)
        resp2 = await client.post("/webhooks/forgejo", content=body2, headers=headers2)
        assert resp2.status_code == 200

        # Title should still be the first value
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.title == "First Ingestion"

    async def test_different_sha_triggers_new_ingestion(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """A push with a different SHA triggers ingestion even if entry was already ingested."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        sha1 = "d" * 40
        sha2 = "e" * 40
        entry_yaml_v1 = _build_entry_yaml(entry_id, title="Version One")
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml_v1)

        body1, headers1 = _send_push(client, repo_name, after_sha=sha1)
        await client.post("/webhooks/forgejo", content=body1, headers=headers1)

        # Second push with different SHA and different title
        entry_yaml_v2 = _build_entry_yaml(entry_id, title="Version Two")
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml_v2)

        body2, headers2 = _send_push(client, repo_name, after_sha=sha2)
        resp = await client.post("/webhooks/forgejo", content=body2, headers=headers2)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.title == "Version Two"
            assert entry.current_head_sha == sha2


# ---------------------------------------------------------------------------
# NEV-119: Push Ingestion -- entry.yaml error handling
# ---------------------------------------------------------------------------


class TestIngestionEntryYamlErrors:
    """Scenario: Error conditions during entry.yaml ingestion."""

    async def test_missing_entry_yaml_skips_ingestion_commits_sha(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """If entry.yaml is missing, SHA is set but no metadata fields are updated."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        # Do NOT populate any files -- entry.yaml is missing
        sha = "f" * 40

        body, headers = _send_push(client, repo_name, after_sha=sha)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            # SHA is committed
            assert entry.current_head_sha == sha
            # Title remains the original (not modified by ingestion)
            assert entry.title == "Webhook Target Entry"

    async def test_malformed_entry_yaml_skips_ingestion(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Malformed YAML in entry.yaml skips ingestion, commits SHA only."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = (
            b"not: valid: yaml: [unterminated"
        )
        sha = "a1" * 20

        body, headers = _send_push(client, repo_name, after_sha=sha)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.current_head_sha == sha
            assert entry.title == "Webhook Target Entry"

    async def test_entry_id_mismatch_skips_ingestion(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """If entry_id in YAML does not match repo entry_id, skip ingestion."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        wrong_id = str(uuid4())
        entry_yaml = _build_entry_yaml(wrong_id, title="Wrong ID Entry")
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = entry_yaml.encode()
        sha = "b1" * 20

        body, headers = _send_push(client, repo_name, after_sha=sha)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.current_head_sha == sha
            # Title NOT updated because entry_id mismatch
            assert entry.title == "Webhook Target Entry"

    async def test_entry_yaml_missing_required_fields_skips_ingestion(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """entry.yaml missing required fields (e.g., title) skips ingestion."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        # YAML without title
        incomplete_yaml = yaml.dump({
            "entry_id": f"ent_{entry_id}",
            "schema_version": 1,
            "content_format": "markdown",
            "author": {"id": f"usr_{uuid4()}", "name": "test"},
            "created_at": "2026-03-15T12:00:00+00:00",
        })
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = incomplete_yaml.encode()
        sha = "c1" * 20

        body, headers = _send_push(client, repo_name, after_sha=sha)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.current_head_sha == sha
            assert entry.title == "Webhook Target Entry"

    async def test_always_returns_200_even_on_unhandled_error(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
    ) -> None:
        """Outer try/except wraps entire ingestion to always return 200."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        # Populate with valid YAML but make read_file raise an unexpected error
        # by setting a bytes value that will cause an internal error
        fake_git.files[(UUID(entry_id), ".phiacta/entry.yaml")] = b"\x80\x81\x82"

        sha = "d1" * 20
        body, headers = _send_push(client, repo_name, after_sha=sha)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        # Must still return 200 to prevent Forgejo retry storms
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# NEV-119: Push Ingestion -- README error handling
# ---------------------------------------------------------------------------


class TestIngestionReadmeErrors:
    """Scenario: README file missing or unavailable during ingestion."""

    async def test_missing_readme_sets_content_cache_none(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """If README is missing, content_cache is set to None but metadata still updates."""
        entry_id, repo_name, _ = await _create_entry_for_webhook(client)
        entry_yaml = _build_entry_yaml(
            entry_id, title="Entry With No README", content_format="markdown"
        )
        # Only entry.yaml, no README
        _populate_fake_git(fake_git, entry_id, entry_yaml=entry_yaml)

        body, headers = _send_push(client, repo_name)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_id))
            )
            entry = result.scalar_one()
            assert entry.title == "Entry With No README"
            assert entry.content_cache is None

    async def test_readme_missing_does_not_block_refs_ingestion(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Missing README does not prevent refs.yaml from being ingested."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)
        entry_yaml = _build_entry_yaml(entry_a_id, title="Entry A With Refs")
        refs_yaml = _build_refs_yaml([
            {
                "rel": "cites",
                "target": {"entry_id": f"ent_{entry_b_id}"},
            }
        ])
        # entry.yaml + refs.yaml but NO README
        fake_git.files[(UUID(entry_a_id), ".phiacta/entry.yaml")] = entry_yaml.encode()
        fake_git.files[(UUID(entry_a_id), ".phiacta/refs.yaml")] = refs_yaml.encode()

        body, headers = _send_push(client, repo_a)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            assert len(refs) == 1
            assert refs[0].to_entry_id == UUID(entry_b_id)


# ---------------------------------------------------------------------------
# NEV-119: Push Ingestion -- refs.yaml
# ---------------------------------------------------------------------------


class TestIngestionRefsYamlHappyPath:
    """Scenario: Webhook push ingests refs.yaml and syncs entry_refs."""

    async def test_ingestion_creates_entry_refs_from_refs_yaml(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """refs.yaml with valid refs creates corresponding entry_ref rows."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml = _build_refs_yaml([
            {
                "rel": "cites",
                "target": {"entry_id": f"ent_{entry_b_id}"},
                "note": "Cited in section 3",
            }
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml
        )

        body, headers = _send_push(client, repo_a)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            assert len(refs) == 1
            assert refs[0].to_entry_id == UUID(entry_b_id)
            assert refs[0].rel == "cites"
            assert refs[0].note == "Cited in section 3"

    async def test_ingestion_creates_multiple_refs(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """refs.yaml with multiple entries creates all corresponding entry_ref rows."""
        # Create three entries: A references both B and C
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)
        entry_c_id, _, _ = await _create_entry_for_webhook(client)

        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml = _build_refs_yaml([
            {
                "rel": "cites",
                "target": {"entry_id": f"ent_{entry_b_id}"},
            },
            {
                "rel": "extends",
                "target": {"entry_id": f"ent_{entry_c_id}"},
                "version_sha": "abc123" * 6 + "abcd",
            },
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml
        )

        body, headers = _send_push(client, repo_a)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef)
                .where(EntryRef.from_entry_id == UUID(entry_a_id))
                .order_by(EntryRef.rel)
            )
            refs = list(result.scalars().all())
            assert len(refs) == 2
            rels = {r.rel for r in refs}
            assert rels == {"cites", "extends"}
            targets = {r.to_entry_id for r in refs}
            assert targets == {UUID(entry_b_id), UUID(entry_c_id)}

    async def test_ingestion_replaces_all_outgoing_refs(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Subsequent pushes replace-all outgoing refs (delete old, insert new)."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)
        entry_c_id, _, _ = await _create_entry_for_webhook(client)

        # First push: A -> B
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml_v1 = _build_refs_yaml([
            {"rel": "cites", "target": {"entry_id": f"ent_{entry_b_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml_v1
        )
        body1, headers1 = _send_push(client, repo_a, after_sha="a" * 40)
        await client.post("/webhooks/forgejo", content=body1, headers=headers1)

        # Second push: A -> C (B ref should be deleted)
        refs_yaml_v2 = _build_refs_yaml([
            {"rel": "extends", "target": {"entry_id": f"ent_{entry_c_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml_v2
        )
        body2, headers2 = _send_push(client, repo_a, after_sha="b" * 40)
        await client.post("/webhooks/forgejo", content=body2, headers=headers2)

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            assert len(refs) == 1
            assert refs[0].to_entry_id == UUID(entry_c_id)
            assert refs[0].rel == "extends"

    async def test_ingestion_ref_with_version_sha(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """version_sha from refs.yaml is stored on the entry_ref row."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)
        version_sha = "f0f0f0" * 6 + "f0f0"
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml = _build_refs_yaml([
            {
                "rel": "cites",
                "target": {"entry_id": f"ent_{entry_b_id}"},
                "version_sha": version_sha,
            }
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml
        )

        body, headers = _send_push(client, repo_a)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            ref = result.scalar_one()
            assert ref.version_sha == version_sha


class TestIngestionRefsYamlMissingAndEmpty:
    """Scenario: refs.yaml is missing or has an empty refs list."""

    async def test_missing_refs_yaml_deletes_existing_outgoing_refs(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """If refs.yaml is absent, all existing outgoing refs are deleted (YAML is source of truth)."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)

        # First push: establish a ref A -> B
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml = _build_refs_yaml([
            {"rel": "cites", "target": {"entry_id": f"ent_{entry_b_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml
        )
        body1, headers1 = _send_push(client, repo_a, after_sha="a" * 40)
        await client.post("/webhooks/forgejo", content=body1, headers=headers1)

        # Verify ref exists
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            assert len(list(result.scalars().all())) == 1

        # Second push: no refs.yaml at all
        _populate_fake_git(fake_git, entry_a_id, entry_yaml=entry_yaml)
        body2, headers2 = _send_push(client, repo_a, after_sha="b" * 40)
        await client.post("/webhooks/forgejo", content=body2, headers=headers2)

        # Refs should be deleted
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            assert len(refs) == 0

    async def test_empty_refs_list_deletes_existing_outgoing_refs(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """refs.yaml with ``refs: []`` deletes all outgoing refs."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)

        # First push with a ref
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml_v1 = _build_refs_yaml([
            {"rel": "cites", "target": {"entry_id": f"ent_{entry_b_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml_v1
        )
        body1, headers1 = _send_push(client, repo_a, after_sha="a" * 40)
        await client.post("/webhooks/forgejo", content=body1, headers=headers1)

        # Second push with empty refs
        refs_yaml_v2 = _build_refs_yaml([])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml_v2
        )
        body2, headers2 = _send_push(client, repo_a, after_sha="b" * 40)
        await client.post("/webhooks/forgejo", content=body2, headers=headers2)

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            assert len(refs) == 0


class TestIngestionRefsYamlErrors:
    """Scenario: Error conditions during refs.yaml ingestion."""

    async def test_self_ref_filtered_out(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Self-referential entries in refs.yaml are silently skipped."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml = _build_refs_yaml([
            # Self-ref -- should be filtered
            {"rel": "cites", "target": {"entry_id": f"ent_{entry_a_id}"}},
            # Valid ref -- should be kept
            {"rel": "extends", "target": {"entry_id": f"ent_{entry_b_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml
        )

        body, headers = _send_push(client, repo_a)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            # Only the valid ref, not the self-ref
            assert len(refs) == 1
            assert refs[0].to_entry_id == UUID(entry_b_id)

    async def test_ref_to_nonexistent_entry_skipped(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Refs to entries that do not exist in the DB are skipped with warning."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)
        nonexistent_id = str(uuid4())
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml = _build_refs_yaml([
            # Ref to non-existent entry -- should be skipped
            {"rel": "cites", "target": {"entry_id": f"ent_{nonexistent_id}"}},
            # Valid ref -- should be kept
            {"rel": "extends", "target": {"entry_id": f"ent_{entry_b_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml
        )

        body, headers = _send_push(client, repo_a)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            assert len(refs) == 1
            assert refs[0].to_entry_id == UUID(entry_b_id)

    async def test_malformed_refs_yaml_leaves_refs_unchanged(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Malformed refs.yaml leaves existing refs UNCHANGED (no delete)."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)

        # First push: establish a ref
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml_v1 = _build_refs_yaml([
            {"rel": "cites", "target": {"entry_id": f"ent_{entry_b_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml_v1
        )
        body1, headers1 = _send_push(client, repo_a, after_sha="a" * 40)
        await client.post("/webhooks/forgejo", content=body1, headers=headers1)

        # Second push: malformed refs.yaml
        fake_git.files[(UUID(entry_a_id), ".phiacta/entry.yaml")] = entry_yaml.encode()
        fake_git.files[(UUID(entry_a_id), ".phiacta/refs.yaml")] = (
            b"refs: [not: valid: yaml: unterminated"
        )
        body2, headers2 = _send_push(client, repo_a, after_sha="b" * 40)
        await client.post("/webhooks/forgejo", content=body2, headers=headers2)

        # Original ref should still exist (not deleted)
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            assert len(refs) == 1
            assert refs[0].to_entry_id == UUID(entry_b_id)

    async def test_only_self_refs_results_in_empty_refs(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """If refs.yaml contains only self-refs, all get filtered and result is empty."""
        entry_a_id, repo_a, _, _ = await _create_two_entries_for_refs(client)
        entry_yaml = _build_entry_yaml(entry_a_id)
        refs_yaml = _build_refs_yaml([
            {"rel": "cites", "target": {"entry_id": f"ent_{entry_a_id}"}},
            {"rel": "extends", "target": {"entry_id": f"ent_{entry_a_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml, refs_yaml=refs_yaml
        )

        body, headers = _send_push(client, repo_a)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        async with e2e_session_factory() as session:
            result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(result.scalars().all())
            assert len(refs) == 0


# ---------------------------------------------------------------------------
# NEV-119: Push Ingestion -- refs don't affect other entries' refs
# ---------------------------------------------------------------------------


class TestIngestionRefsIsolation:
    """Scenario: Ingestion only affects the pushed entry's outgoing refs,
    not any other entry's refs."""

    async def test_ingestion_does_not_delete_other_entries_refs(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Replace-all only deletes outgoing refs for the entry being ingested,
        not for any other entry."""
        # Create entries A, B, C
        entry_a_id, repo_a, entry_b_id, repo_b = await _create_two_entries_for_refs(
            client
        )
        entry_c_id, _, _ = await _create_entry_for_webhook(client)

        # Push to entry B: B -> C ref
        entry_yaml_b = _build_entry_yaml(entry_b_id)
        refs_yaml_b = _build_refs_yaml([
            {"rel": "cites", "target": {"entry_id": f"ent_{entry_c_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_b_id, entry_yaml=entry_yaml_b, refs_yaml=refs_yaml_b
        )
        body_b, headers_b = _send_push(client, repo_b, after_sha="a" * 40)
        await client.post("/webhooks/forgejo", content=body_b, headers=headers_b)

        # Now push to entry A with refs A -> C
        entry_yaml_a = _build_entry_yaml(entry_a_id)
        refs_yaml_a = _build_refs_yaml([
            {"rel": "extends", "target": {"entry_id": f"ent_{entry_c_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id, entry_yaml=entry_yaml_a, refs_yaml=refs_yaml_a
        )
        body_a, headers_a = _send_push(client, repo_a, after_sha="b" * 40)
        await client.post("/webhooks/forgejo", content=body_a, headers=headers_a)

        # Both entries should still have their refs
        async with e2e_session_factory() as session:
            result_a = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs_a = list(result_a.scalars().all())
            assert len(refs_a) == 1
            assert refs_a[0].rel == "extends"

            result_b = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_b_id))
            )
            refs_b = list(result_b.scalars().all())
            assert len(refs_b) == 1
            assert refs_b[0].rel == "cites"


# ---------------------------------------------------------------------------
# NEV-119: Full Journey E2E
# ---------------------------------------------------------------------------


class TestIngestionFullJourney:
    """Scenario: Complete ingestion journey with entry.yaml, README, and refs.yaml
    all present and valid."""

    async def test_full_ingestion_journey(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Full push ingestion: entry.yaml + README.md + refs.yaml all processed atomically."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)
        entry_c_id, _, _ = await _create_entry_for_webhook(client)
        sha = "abcdef" * 6 + "abcd"

        entry_yaml = _build_entry_yaml(
            entry_a_id,
            title="Quantum Entanglement: A Comprehensive Study",
            content_format="markdown",
            tags=["quantum", "entanglement", "physics"],
            summary="An in-depth analysis of quantum entanglement.",
            license_="CC-BY-SA-4.0",
            layout_hint="research-paper",
            schema_version=2,
        )
        readme = "# Quantum Entanglement\n\nA study of EPR pairs and Bell inequalities.\n"
        refs_yaml = _build_refs_yaml([
            {
                "rel": "cites",
                "target": {"entry_id": f"ent_{entry_b_id}"},
                "note": "Original EPR paper",
            },
            {
                "rel": "extends",
                "target": {"entry_id": f"ent_{entry_c_id}"},
                "version_sha": "deadbeef" * 5,
            },
        ])
        _populate_fake_git(
            fake_git, entry_a_id,
            entry_yaml=entry_yaml,
            readme_content=readme,
            refs_yaml=refs_yaml,
        )

        body, headers = _send_push(client, repo_a, after_sha=sha)
        resp = await client.post("/webhooks/forgejo", content=body, headers=headers)
        assert resp.status_code == 200

        # Verify ALL entry fields
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_a_id))
            )
            entry = result.scalar_one()
            assert entry.title == "Quantum Entanglement: A Comprehensive Study"
            assert entry.content_format == "markdown"
            assert entry.tags == ["quantum", "entanglement", "physics"]
            assert entry.summary == "An in-depth analysis of quantum entanglement."
            assert entry.license == "CC-BY-SA-4.0"
            assert entry.layout_hint == "research-paper"
            assert entry.schema_version == 2
            assert entry.content_cache == readme
            assert entry.current_head_sha == sha

            # Verify ALL refs
            ref_result = await session.execute(
                select(EntryRef)
                .where(EntryRef.from_entry_id == UUID(entry_a_id))
                .order_by(EntryRef.rel)
            )
            refs = list(ref_result.scalars().all())
            assert len(refs) == 2

            cites_ref = next(r for r in refs if r.rel == "cites")
            assert cites_ref.to_entry_id == UUID(entry_b_id)
            assert cites_ref.note == "Original EPR paper"

            extends_ref = next(r for r in refs if r.rel == "extends")
            assert extends_ref.to_entry_id == UUID(entry_c_id)
            assert extends_ref.version_sha == "deadbeef" * 5

    async def test_sequential_pushes_update_incrementally(
        self,
        client: httpx.AsyncClient,
        fake_git: FakeGitService,
        e2e_session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Two sequential pushes with different SHAs each update the entry."""
        entry_a_id, repo_a, entry_b_id, _ = await _create_two_entries_for_refs(client)

        # First push
        entry_yaml_v1 = _build_entry_yaml(
            entry_a_id, title="Version 1", summary="First version"
        )
        readme_v1 = "# Version 1 Content\n"
        _populate_fake_git(
            fake_git, entry_a_id,
            entry_yaml=entry_yaml_v1,
            readme_content=readme_v1,
        )
        body1, headers1 = _send_push(client, repo_a, after_sha="1" * 40)
        await client.post("/webhooks/forgejo", content=body1, headers=headers1)

        # Verify v1
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_a_id))
            )
            entry = result.scalar_one()
            assert entry.title == "Version 1"
            assert entry.content_cache == readme_v1
            assert entry.current_head_sha == "1" * 40

        # Second push with different content
        entry_yaml_v2 = _build_entry_yaml(
            entry_a_id,
            title="Version 2 Updated",
            summary="Updated version",
            tags=["new-tag"],
        )
        readme_v2 = "# Version 2 Updated Content\n"
        refs_yaml_v2 = _build_refs_yaml([
            {"rel": "cites", "target": {"entry_id": f"ent_{entry_b_id}"}},
        ])
        _populate_fake_git(
            fake_git, entry_a_id,
            entry_yaml=entry_yaml_v2,
            readme_content=readme_v2,
            refs_yaml=refs_yaml_v2,
        )
        body2, headers2 = _send_push(client, repo_a, after_sha="2" * 40)
        await client.post("/webhooks/forgejo", content=body2, headers=headers2)

        # Verify v2
        async with e2e_session_factory() as session:
            result = await session.execute(
                select(Entry).where(Entry.id == UUID(entry_a_id))
            )
            entry = result.scalar_one()
            assert entry.title == "Version 2 Updated"
            assert entry.summary == "Updated version"
            assert entry.tags == ["new-tag"]
            assert entry.content_cache == readme_v2
            assert entry.current_head_sha == "2" * 40

            ref_result = await session.execute(
                select(EntryRef).where(EntryRef.from_entry_id == UUID(entry_a_id))
            )
            refs = list(ref_result.scalars().all())
            assert len(refs) == 1
            assert refs[0].to_entry_id == UUID(entry_b_id)
