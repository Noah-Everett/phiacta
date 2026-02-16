# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.claim import Claim
from phiacta.models.namespace import Namespace
from phiacta.repositories.claim_repository import ClaimRepository
from tests.conftest import make_agent, make_claim, make_namespace

needs_db = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL not set; skipping integration test",
)


@needs_db
class TestCreateAndGetClaim:
    async def test_create_and_get_claim(self, db_session: AsyncSession) -> None:
        # Set up prerequisites
        agent_kwargs = make_agent()
        agent = Agent(**agent_kwargs)
        db_session.add(agent)

        ns_kwargs = make_namespace()
        ns = Namespace(**ns_kwargs)
        db_session.add(ns)
        await db_session.flush()

        repo = ClaimRepository(db_session)
        claim_kwargs = make_claim(namespace_id=ns.id, created_by=agent.id)
        claim = Claim(**claim_kwargs)
        created = await repo.create(claim)

        assert created.id == claim.id
        assert created.content == "Test claim content"

        fetched = await repo.get_by_id(claim.id)
        assert fetched is not None
        assert fetched.id == claim.id
        assert fetched.claim_type == "assertion"

    async def test_get_nonexistent_returns_none(self, db_session: AsyncSession) -> None:
        repo = ClaimRepository(db_session)
        result = await repo.get_by_id(uuid4())
        assert result is None


@needs_db
class TestGetByLineage:
    async def test_get_by_lineage(self, db_session: AsyncSession) -> None:
        agent = Agent(**make_agent())
        ns = Namespace(**make_namespace())
        db_session.add(agent)
        db_session.add(ns)
        await db_session.flush()

        repo = ClaimRepository(db_session)
        lineage_id = uuid4()

        claim_v1 = Claim(
            **make_claim(
                namespace_id=ns.id,
                created_by=agent.id,
                lineage_id=lineage_id,
                version=1,
                content="Version 1",
            )
        )
        claim_v2 = Claim(
            **make_claim(
                namespace_id=ns.id,
                created_by=agent.id,
                lineage_id=lineage_id,
                version=2,
                content="Version 2",
            )
        )
        await repo.create(claim_v1)
        await repo.create(claim_v2)

        results = await repo.get_by_lineage(lineage_id)
        assert len(results) == 2
        # Should be ordered by version DESC
        assert results[0].version == 2
        assert results[1].version == 1


@needs_db
class TestGetLatestVersion:
    async def test_get_latest_version(self, db_session: AsyncSession) -> None:
        agent = Agent(**make_agent())
        ns = Namespace(**make_namespace())
        db_session.add(agent)
        db_session.add(ns)
        await db_session.flush()

        repo = ClaimRepository(db_session)
        lineage_id = uuid4()

        claim_v1 = Claim(
            **make_claim(
                namespace_id=ns.id,
                created_by=agent.id,
                lineage_id=lineage_id,
                version=1,
            )
        )
        claim_v3 = Claim(
            **make_claim(
                namespace_id=ns.id,
                created_by=agent.id,
                lineage_id=lineage_id,
                version=3,
            )
        )
        await repo.create(claim_v1)
        await repo.create(claim_v3)

        latest = await repo.get_latest_version(lineage_id)
        assert latest is not None
        assert latest.version == 3

    async def test_get_latest_version_empty(self, db_session: AsyncSession) -> None:
        repo = ClaimRepository(db_session)
        result = await repo.get_latest_version(uuid4())
        assert result is None


@needs_db
class TestListClaimsWithFilters:
    async def test_list_claims_with_filters(self, db_session: AsyncSession) -> None:
        agent = Agent(**make_agent())
        ns = Namespace(**make_namespace())
        db_session.add(agent)
        db_session.add(ns)
        await db_session.flush()

        repo = ClaimRepository(db_session)

        assertion = Claim(
            **make_claim(
                namespace_id=ns.id,
                created_by=agent.id,
                claim_type="assertion",
                content="An assertion",
            )
        )
        theorem = Claim(
            **make_claim(
                namespace_id=ns.id,
                created_by=agent.id,
                claim_type="theorem",
                content="A theorem",
            )
        )
        await repo.create(assertion)
        await repo.create(theorem)

        # Filter by claim_type
        assertions = await repo.list_claims(claim_type="assertion")
        assert len(assertions) >= 1
        assert all(c.claim_type == "assertion" for c in assertions)

        theorems = await repo.list_claims(claim_type="theorem")
        assert len(theorems) >= 1
        assert all(c.claim_type == "theorem" for c in theorems)

        # Filter by namespace_id
        by_ns = await repo.list_claims(namespace_id=ns.id)
        assert len(by_ns) >= 2

        # Combined filters
        combined = await repo.list_claims(claim_type="assertion", namespace_id=ns.id)
        assert len(combined) >= 1
        assert all(c.claim_type == "assertion" for c in combined)

    async def test_list_claims_pagination(self, db_session: AsyncSession) -> None:
        agent = Agent(**make_agent())
        ns = Namespace(**make_namespace())
        db_session.add(agent)
        db_session.add(ns)
        await db_session.flush()

        repo = ClaimRepository(db_session)

        for i in range(5):
            claim = Claim(
                **make_claim(
                    namespace_id=ns.id,
                    created_by=agent.id,
                    content=f"Claim {i}",
                )
            )
            await repo.create(claim)

        page1 = await repo.list_claims(limit=2, offset=0)
        page2 = await repo.list_claims(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0].id != page2[0].id
