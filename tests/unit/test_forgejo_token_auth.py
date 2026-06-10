# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for Forgejo API-token authentication.

The backend authenticates to Forgejo on every request. Using HTTP BasicAuth
makes Forgejo run its password KDF per request (~180ms); an API token is a
fast lookup (~15-40ms). These tests lock the auth-selection contract:

- a configured token => ``Authorization: token <sha1>`` (no BasicAuth)
- no token           => BasicAuth (the safe fallback — never breaks)
- a token file       => read lazily (it is written by Forgejo at bootstrap,
                        possibly after the backend has already started)
- a token Forgejo rejects (rotated on restart) => drop it, retry once with
  BasicAuth, and stop reusing the dead token.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from phiacta.core.services.git_service import ForgejoGitService


def _make_service(*, token: str = "", token_file: str = "") -> ForgejoGitService:
    with patch("phiacta.core.services.git_service.get_settings") as mock_settings:
        settings = MagicMock()
        settings.forgejo_url = "http://forgejo:3000"
        settings.forgejo_org = "phiacta"
        settings.forgejo_admin_user = "phiacta-admin"
        settings.forgejo_admin_password = "secret"
        settings.forgejo_webhook_secret = "webhook-secret"
        settings.forgejo_admin_token = token
        settings.forgejo_admin_token_file = token_file
        mock_settings.return_value = settings
        return ForgejoGitService()


def _stub_client(svc: ForgejoGitService, status: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    svc._client = AsyncMock()
    svc._client.request = AsyncMock(return_value=resp)
    return resp


def _headers(call) -> dict:
    return call.kwargs.get("headers") or {}


class TestTokenAuthSelection:
    async def test_token_header_when_token_configured(self) -> None:
        svc = _make_service(token="abc123")
        _stub_client(svc)

        await svc._request("GET", "/x")

        call = svc._client.request.call_args
        assert _headers(call)["Authorization"] == "token abc123"
        # No BasicAuth when a token is used.
        assert call.kwargs.get("auth") is None

    async def test_basic_auth_when_no_token(self) -> None:
        svc = _make_service(token="")
        _stub_client(svc)

        await svc._request("GET", "/x")

        call = svc._client.request.call_args
        assert "Authorization" not in _headers(call)
        assert isinstance(call.kwargs.get("auth"), httpx.BasicAuth)

    async def test_token_and_sudo_both_sent(self) -> None:
        svc = _make_service(token="tok")
        _stub_client(svc)

        await svc._request("GET", "/x", sudo_username="alice")

        h = _headers(svc._client.request.call_args)
        assert h["Sudo"] == "alice"
        assert h["Authorization"] == "token tok"

    async def test_no_sudo_no_token_sends_no_headers(self) -> None:
        # Preserves the prior contract: nothing to add => headers is None.
        svc = _make_service(token="")
        _stub_client(svc)

        await svc._request("GET", "/x")

        assert svc._client.request.call_args.kwargs.get("headers") is None


class TestTokenFile:
    async def test_reads_token_from_file(self, tmp_path) -> None:
        f = tmp_path / "admin-token"
        f.write_text("filetoken\n")  # trailing newline must be stripped
        svc = _make_service(token="", token_file=str(f))
        _stub_client(svc)

        await svc._request("GET", "/x")

        assert _headers(svc._client.request.call_args)["Authorization"] == "token filetoken"

    async def test_token_file_read_lazily_when_absent_then_present(self, tmp_path) -> None:
        # The file is written by Forgejo's entrypoint, which may finish after
        # the backend starts. First request (no file) must fall back to
        # BasicAuth; a later request picks up the token once the file appears.
        f = tmp_path / "admin-token"
        svc = _make_service(token="", token_file=str(f))
        _stub_client(svc)

        await svc._request("GET", "/x")
        first = svc._client.request.call_args
        assert isinstance(first.kwargs.get("auth"), httpx.BasicAuth)
        assert "Authorization" not in _headers(first)

        f.write_text("late-token")
        await svc._request("GET", "/y")
        second = svc._client.request.call_args
        assert _headers(second)["Authorization"] == "token late-token"
        assert second.kwargs.get("auth") is None


class TestTokenSelfHeal:
    async def test_401_with_token_retries_with_basic_auth(self) -> None:
        svc = _make_service(token="stale")
        r401 = MagicMock(spec=httpx.Response)
        r401.status_code = 401
        r200 = MagicMock(spec=httpx.Response)
        r200.status_code = 200
        svc._client = AsyncMock()
        svc._client.request = AsyncMock(side_effect=[r401, r200])

        resp = await svc._request("GET", "/x")

        assert resp.status_code == 200
        assert svc._client.request.await_count == 2
        retry = svc._client.request.call_args_list[1]
        assert isinstance(retry.kwargs.get("auth"), httpx.BasicAuth)
        assert "Authorization" not in _headers(retry)

    async def test_rejected_token_not_reused_on_next_request(self) -> None:
        # After a token is rejected, subsequent requests should go straight to
        # BasicAuth rather than re-sending (and re-failing on) the dead token.
        svc = _make_service(token="stale")
        r401 = MagicMock(spec=httpx.Response)
        r401.status_code = 401
        r200 = MagicMock(spec=httpx.Response)
        r200.status_code = 200
        svc._client = AsyncMock()
        svc._client.request = AsyncMock(side_effect=[r401, r200, r200])

        await svc._request("GET", "/x")  # 401 then basic-retry (2 calls)
        await svc._request("GET", "/y")  # should be a single basic call

        assert svc._client.request.await_count == 3
        third = svc._client.request.call_args_list[2]
        assert isinstance(third.kwargs.get("auth"), httpx.BasicAuth)
        assert "Authorization" not in _headers(third)
