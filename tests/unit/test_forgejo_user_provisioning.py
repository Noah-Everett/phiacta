# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for Forgejo user provisioning and Sudo header support."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from phiacta.core.services.git_service import (
    ForgejoError,
    ForgejoGitService,
    RepoNotFoundError,
)


# --- Helpers ----------------------------------------------------------------


def _make_user(*, forgejo_user_id: int | None = None) -> MagicMock:
    user = MagicMock()
    user.id = uuid4()
    user.username = "testuser"
    user.forgejo_user_id = forgejo_user_id
    return user


def _make_service() -> ForgejoGitService:
    """Create a ForgejoGitService with stubbed settings."""
    with patch("phiacta.core.services.git_service.get_settings") as mock_settings:
        settings = MagicMock()
        settings.forgejo_url = "http://forgejo:3000"
        settings.forgejo_org = "phiacta"
        settings.forgejo_admin_user = "phiacta-admin"
        settings.forgejo_admin_password = "secret"
        settings.forgejo_webhook_secret = "webhook-secret"
        mock_settings.return_value = settings
        return ForgejoGitService()


# --- Sudo header tests ------------------------------------------------------


class TestSudoHeader:
    async def test_sudo_header_sent_when_username_provided(self) -> None:
        svc = _make_service()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        svc._client = AsyncMock()
        svc._client.request = AsyncMock(return_value=mock_response)

        await svc._request("GET", "/test", sudo_username="alice")

        svc._client.request.assert_awaited_once()
        call_kwargs = svc._client.request.call_args
        assert call_kwargs.kwargs.get("headers") == {"Sudo": "alice"}

    async def test_no_sudo_header_when_username_is_none(self) -> None:
        svc = _make_service()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        svc._client = AsyncMock()
        svc._client.request = AsyncMock(return_value=mock_response)

        await svc._request("GET", "/test")

        call_kwargs = svc._client.request.call_args
        assert call_kwargs.kwargs.get("headers") is None


# --- ensure_forgejo_user tests -----------------------------------------------


class TestEnsureForgejoUser:
    async def test_noop_when_already_provisioned(self) -> None:
        svc = _make_service()
        user = _make_user(forgejo_user_id=42)
        db = AsyncMock()

        await svc.ensure_forgejo_user(user, db)

        # Should not make any HTTP calls
        db.add.assert_not_called()
        db.flush.assert_not_awaited()

    async def test_creates_forgejo_user_and_stores_id(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2  # pre-cache to avoid extra lookup
        user = _make_user()
        db = AsyncMock()

        # Mock _request to return success for user creation and team membership
        create_resp = MagicMock()
        create_resp.json.return_value = {"id": 99}
        team_resp = MagicMock()

        call_count = 0
        async def fake_request(method, path, **kwargs):
            nonlocal call_count
            call_count += 1
            if method == "POST" and path == "/admin/users":
                return create_resp
            if method == "PUT" and path == "/teams/2/members/testuser":
                return team_resp
            raise AssertionError(f"Unexpected call: {method} {path}")

        svc._request = fake_request

        await svc.ensure_forgejo_user(user, db)

        assert user.forgejo_user_id == 99
        db.add.assert_called_once_with(user)
        db.flush.assert_awaited_once()

    async def test_reuses_existing_forgejo_user_on_conflict(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2
        user = _make_user()
        db = AsyncMock()

        # First call (POST /admin/users) raises conflict,
        # second call (GET /users/{username}) returns existing user
        lookup_resp = MagicMock()
        lookup_resp.json.return_value = {"id": 77}
        team_resp = MagicMock()

        async def fake_request(method, path, **kwargs):
            if method == "POST" and path == "/admin/users":
                raise ForgejoError("422: user already exists")
            if method == "GET" and path == f"/users/{user.username}":
                return lookup_resp
            if method == "PUT" and path == "/teams/2/members/testuser":
                return team_resp
            raise AssertionError(f"Unexpected call: {method} {path}")

        svc._request = fake_request

        await svc.ensure_forgejo_user(user, db)

        assert user.forgejo_user_id == 77
        db.flush.assert_awaited_once()

    async def test_raises_when_create_and_lookup_both_fail(self) -> None:
        svc = _make_service()
        user = _make_user()
        db = AsyncMock()

        async def fake_request(method, path, **kwargs):
            if method == "POST" and path == "/admin/users":
                raise ForgejoError("422: user already exists")
            if method == "GET" and path == f"/users/{user.username}":
                raise RepoNotFoundError("User not found")
            raise AssertionError(f"Unexpected call: {method} {path}")

        svc._request = fake_request

        with pytest.raises(RepoNotFoundError):
            await svc.ensure_forgejo_user(user, db)

        assert user.forgejo_user_id is None
        db.flush.assert_not_awaited()

    async def test_team_add_failure_raises(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2
        user = _make_user()
        db = AsyncMock()

        create_resp = MagicMock()
        create_resp.json.return_value = {"id": 55}

        async def fake_request(method, path, **kwargs):
            if method == "POST" and path == "/admin/users":
                return create_resp
            if method == "PUT" and path == "/teams/2/members/testuser":
                raise ForgejoError("500: internal error")
            raise AssertionError(f"Unexpected call: {method} {path}")

        svc._request = fake_request

        with pytest.raises(ForgejoError):
            await svc.ensure_forgejo_user(user, db)

        # User should NOT be provisioned if team membership fails
        assert user.forgejo_user_id is None
        db.flush.assert_not_awaited()

    async def test_creates_user_with_synthetic_email(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2
        user = _make_user()
        db = AsyncMock()

        captured_payload: dict = {}
        create_resp = MagicMock()
        create_resp.json.return_value = {"id": 10}
        team_resp = MagicMock()

        async def fake_request(method, path, **kwargs):
            if method == "POST" and path == "/admin/users":
                captured_payload.update(kwargs.get("json", {}))
                return create_resp
            if method == "PUT" and path == "/teams/2/members/testuser":
                return team_resp
            raise AssertionError(f"Unexpected call: {method} {path}")

        svc._request = fake_request

        await svc.ensure_forgejo_user(user, db)

        assert captured_payload["username"] == "testuser"
        assert captured_payload["email"] == f"{user.id}@phiacta.local"
        assert captured_payload["must_change_password"] is False
        assert captured_payload["visibility"] == "private"
        # Password should be set (random, non-empty)
        assert len(captured_payload["password"]) > 0


# --- sudo_username passthrough tests ----------------------------------------


class TestSudoPassthrough:
    """Verify that methods forward sudo_username to _request()."""

    async def test_create_issue_passes_sudo(self) -> None:
        svc = _make_service()
        resp = MagicMock()
        resp.json.return_value = {
            "number": 1, "title": "t", "body": "", "state": "open",
            "user": {"login": "alice"}, "comments": 0,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "closed_at": None,
        }
        svc._request = AsyncMock(return_value=resp)

        await svc.create_issue(uuid4(), "t", "", sudo_username="alice")

        svc._request.assert_awaited_once()
        assert svc._request.call_args.kwargs["sudo_username"] == "alice"

    async def test_create_issue_comment_passes_sudo(self) -> None:
        svc = _make_service()
        resp = MagicMock()
        resp.json.return_value = {
            "id": 1, "body": "hi", "user": {"login": "bob"},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        svc._request = AsyncMock(return_value=resp)

        await svc.create_issue_comment(uuid4(), 1, "hi", sudo_username="bob")

        assert svc._request.call_args.kwargs["sudo_username"] == "bob"

    async def test_close_issue_passes_sudo(self) -> None:
        svc = _make_service()
        resp = MagicMock()
        resp.status_code = 200
        svc._request = AsyncMock(return_value=resp)

        await svc.close_issue(uuid4(), 1, sudo_username="carol")

        assert svc._request.call_args.kwargs["sudo_username"] == "carol"

    async def test_create_pull_request_passes_sudo(self) -> None:
        svc = _make_service()
        resp = MagicMock()
        resp.json.return_value = {
            "number": 1, "title": "t", "body": "", "state": "open",
            "draft": False, "head": {"ref": "feat", "sha": "abc"},
            "base": {"ref": "main", "sha": "def"},
            "user": {"login": "dave"},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "merged_at": None,
        }
        svc._request = AsyncMock(return_value=resp)

        await svc.create_pull_request(
            uuid4(), "t", "", "feat", sudo_username="dave",
        )

        assert svc._request.call_args.kwargs["sudo_username"] == "dave"

    async def test_merge_pull_request_passes_sudo(self) -> None:
        svc = _make_service()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b'{"sha": "abc123"}'
        resp.json.return_value = {"sha": "abc123"}
        svc._request = AsyncMock(return_value=resp)

        await svc.merge_pull_request(uuid4(), 1, sudo_username="eve")

        # First call is the merge, second may be a re-fetch
        first_call = svc._request.call_args_list[0]
        assert first_call.kwargs["sudo_username"] == "eve"

    async def test_close_pull_request_passes_sudo(self) -> None:
        svc = _make_service()
        resp = MagicMock()
        resp.status_code = 200
        svc._request = AsyncMock(return_value=resp)

        await svc.close_pull_request(uuid4(), 1, sudo_username="frank")

        assert svc._request.call_args.kwargs["sudo_username"] == "frank"
