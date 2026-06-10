# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Tests for ForgejoGitService.run_startup_migrations()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from phiacta.core.services.git_service import ForgejoGitService


def _make_service() -> ForgejoGitService:
    with patch("phiacta.core.services.git_service.get_settings") as mock_settings:
        settings = MagicMock()
        settings.forgejo_url = "http://forgejo:3000"
        settings.forgejo_org = "phiacta"
        settings.forgejo_admin_user = "phiacta-admin"
        settings.forgejo_admin_password = "secret"
        settings.forgejo_webhook_secret = "webhook-secret"
        settings.forgejo_admin_token = ""
        settings.forgejo_admin_token_file = ""
        mock_settings.return_value = settings
        return ForgejoGitService()


def _ok(data: list | dict) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = data
    return resp


# Default team data — units already correct (no patch needed)
_TEAM_OK = {"units": ["repo.code", "repo.issues", "repo.pulls"]}
# Team missing repo.pulls — needs patching
_TEAM_MISSING_PULLS = {"units": ["repo.issues"]}


class TestRunStartupMigrations:
    async def test_patches_repos_missing_pull_requests(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2

        repos = [
            {"name": "repo-a", "has_pull_requests": True},
            {"name": "repo-b", "has_pull_requests": False},
        ]

        calls: list[tuple[str, str]] = []

        async def fake_request(method, path, **kwargs):
            calls.append((method, path))
            if method == "GET" and path == "/teams/2":
                return _ok(_TEAM_OK)
            if method == "GET" and path == "/orgs/phiacta/repos":
                return _ok(repos)
            if method == "GET" and path == "/teams/2/repos":
                return _ok([{"name": "repo-a"}, {"name": "repo-b"}])
            if method == "GET" and path == "/teams/2/members":
                return _ok([])
            if method == "GET" and path == "/admin/users":
                return _ok([])
            if method == "PATCH":
                return _ok({})
            raise AssertionError(f"Unexpected: {method} {path}")

        svc._request = fake_request

        counts = await svc.run_startup_migrations()

        assert counts["pull_requests_enabled"] == 1
        assert ("PATCH", "/repos/phiacta/repo-b") in calls
        assert ("PATCH", "/repos/phiacta/repo-a") not in calls

    async def test_patches_team_units_when_pulls_missing(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2

        calls: list[tuple[str, str, dict]] = []

        async def fake_request(method, path, **kwargs):
            calls.append((method, path, kwargs.get("json", {})))
            if method == "GET" and path == "/teams/2":
                return _ok(_TEAM_MISSING_PULLS)
            if method == "GET" and path == "/orgs/phiacta/repos":
                return _ok([])
            if method == "GET" and path == "/teams/2/repos":
                return _ok([])
            if method == "GET" and path == "/teams/2/members":
                return _ok([])
            if method == "GET" and path == "/admin/users":
                return _ok([])
            if method == "PATCH":
                return _ok({})
            raise AssertionError(f"Unexpected: {method} {path}")

        svc._request = fake_request

        counts = await svc.run_startup_migrations()

        assert counts["team_units_patched"] == 1
        # Find the PATCH call to /teams/2
        patch_calls = [(m, p, j) for m, p, j in calls if m == "PATCH" and p == "/teams/2"]
        assert len(patch_calls) == 1
        patched_units = set(patch_calls[0][2]["units"])
        assert "repo.pulls" in patched_units
        assert "repo.issues" in patched_units

    async def test_adds_repos_to_members_team(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2

        repos = [
            {"name": "old-repo", "has_pull_requests": True},
            {"name": "new-repo", "has_pull_requests": True},
        ]

        calls: list[tuple[str, str]] = []

        async def fake_request(method, path, **kwargs):
            calls.append((method, path))
            if method == "GET" and path == "/teams/2":
                return _ok(_TEAM_OK)
            if method == "GET" and path == "/orgs/phiacta/repos":
                return _ok(repos)
            if method == "GET" and path == "/teams/2/repos":
                return _ok([{"name": "old-repo"}])
            if method == "GET" and path == "/teams/2/members":
                return _ok([])
            if method == "GET" and path == "/admin/users":
                return _ok([])
            if method == "PUT":
                return _ok({})
            raise AssertionError(f"Unexpected: {method} {path}")

        svc._request = fake_request

        counts = await svc.run_startup_migrations()

        assert counts["repos_added_to_team"] == 1
        assert ("PUT", "/teams/2/repos/phiacta/new-repo") in calls
        assert ("PUT", "/teams/2/repos/phiacta/old-repo") not in calls

    async def test_adds_provisioned_users_to_members_team(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2

        users = [
            {"login": "alice", "email": "abc@phiacta.local"},
            {"login": "bob", "email": "def@phiacta.local"},
            {"login": "phiacta-admin", "email": "admin@example.com"},
        ]

        calls: list[tuple[str, str]] = []

        async def fake_request(method, path, **kwargs):
            calls.append((method, path))
            if method == "GET" and path == "/teams/2":
                return _ok(_TEAM_OK)
            if method == "GET" and path == "/orgs/phiacta/repos":
                return _ok([])
            if method == "GET" and path == "/teams/2/repos":
                return _ok([])
            if method == "GET" and path == "/teams/2/members":
                return _ok([{"login": "bob"}])
            if method == "GET" and path == "/admin/users":
                return _ok(users)
            if method == "PUT":
                return _ok({})
            raise AssertionError(f"Unexpected: {method} {path}")

        svc._request = fake_request

        counts = await svc.run_startup_migrations()

        assert counts["users_added_to_team"] == 1
        assert ("PUT", "/teams/2/members/alice") in calls
        assert ("PUT", "/teams/2/members/bob") not in calls
        assert ("PUT", "/teams/2/members/phiacta-admin") not in calls

    async def test_idempotent_noop(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2

        repos = [{"name": "repo-a", "has_pull_requests": True}]

        mutation_calls: list[tuple[str, str]] = []

        async def fake_request(method, path, **kwargs):
            if method in ("PATCH", "PUT"):
                mutation_calls.append((method, path))
            if method == "GET" and path == "/teams/2":
                return _ok(_TEAM_OK)
            if method == "GET" and path == "/orgs/phiacta/repos":
                return _ok(repos)
            if method == "GET" and path == "/teams/2/repos":
                return _ok([{"name": "repo-a"}])
            if method == "GET" and path == "/teams/2/members":
                return _ok([])
            if method == "GET" and path == "/admin/users":
                return _ok([])
            return _ok({})

        svc._request = fake_request

        counts = await svc.run_startup_migrations()

        assert counts == {
            "team_units_patched": 0,
            "pull_requests_enabled": 0,
            "repos_added_to_team": 0,
            "users_added_to_team": 0,
        }
        assert mutation_calls == []

    async def test_returns_correct_counts(self) -> None:
        svc = _make_service()
        svc._members_team_id = 2

        repos = [
            {"name": "r1", "has_pull_requests": False},
            {"name": "r2", "has_pull_requests": False},
            {"name": "r3", "has_pull_requests": True},
        ]
        users = [
            {"login": "u1", "email": "a@phiacta.local"},
            {"login": "u2", "email": "b@phiacta.local"},
        ]

        async def fake_request(method, path, **kwargs):
            if method == "GET" and path == "/teams/2":
                return _ok(_TEAM_MISSING_PULLS)
            if method == "GET" and path == "/orgs/phiacta/repos":
                return _ok(repos)
            if method == "GET" and path == "/teams/2/repos":
                return _ok([{"name": "r3"}])
            if method == "GET" and path == "/teams/2/members":
                return _ok([])
            if method == "GET" and path == "/admin/users":
                return _ok(users)
            return _ok({})

        svc._request = fake_request

        counts = await svc.run_startup_migrations()

        assert counts["team_units_patched"] == 1
        assert counts["pull_requests_enabled"] == 2
        assert counts["repos_added_to_team"] == 2
        assert counts["users_added_to_team"] == 2
