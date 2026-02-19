# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from phiacta.models.agent import Agent
from phiacta.models.claim import Claim
from phiacta.models.namespace import Namespace
from phiacta.models.reference import Reference
from phiacta.repositories.reference_repository import ReferenceRepository
from tests.conftest import make_agent, make_claim, make_namespace, make_reference

needs_db = pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL not set; skipping integration test",
)


async def _setup_claims(
    db_session: AsyncSession,
) -> tuple[Agent, Namespace, Claim, Claim]:
    """Create prerequisite agent, namespace, and two claims."""
    agent = Agent(**make_agent())
    ns = Namespace(**make_namespace())
    db_session.add(agent)
    db_session.add(ns)
    await db_session.flush()

    claim_a = Claim(**make_claim(namespace_id=ns.id, created_by=agent.id, content="Claim A"))
    claim_b = Claim(**make_claim(namespace_id=ns.id, created_by=agent.id, content="Claim B"))
    db_session.add(claim_a)
    db_session.add(claim_b)
    await db_session.flush()
    return agent, ns, claim_a, claim_b


@needs_db
class TestCreateAndGetReference:
    async def test_create_and_get_reference(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = ReferenceRepository(db_session)
        ref = Reference(
            **make_reference(
                source_uri=f"claim:{claim_a.id}",
                target_uri=f"claim:{claim_b.id}",
                created_by=agent.id,
                role="evidence",
                source_claim_id=claim_a.id,
                target_claim_id=claim_b.id,
            )
        )
        created = await repo.create(ref)
        assert created.id == ref.id

        fetched = await repo.get_by_id(ref.id)
        assert fetched is not None
        assert fetched.source_uri == f"claim:{claim_a.id}"
        assert fetched.target_uri == f"claim:{claim_b.id}"
        assert fetched.role == "evidence"


@needs_db
class TestListByClaimDirection:
    async def test_list_by_claim_both(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = ReferenceRepository(db_session)
        ref = Reference(
            **make_reference(
                source_uri=f"claim:{claim_a.id}",
                target_uri=f"claim:{claim_b.id}",
                created_by=agent.id,
                role="evidence",
                source_claim_id=claim_a.id,
                target_claim_id=claim_b.id,
            )
        )
        await repo.create(ref)

        refs_a = await repo.list_by_claim(claim_a.id, direction="both")
        assert len(refs_a) >= 1

        refs_b = await repo.list_by_claim(claim_b.id, direction="both")
        assert len(refs_b) >= 1

    async def test_list_by_claim_outgoing(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = ReferenceRepository(db_session)
        ref = Reference(
            **make_reference(
                source_uri=f"claim:{claim_a.id}",
                target_uri=f"claim:{claim_b.id}",
                created_by=agent.id,
                role="evidence",
                source_claim_id=claim_a.id,
                target_claim_id=claim_b.id,
            )
        )
        await repo.create(ref)

        outgoing = await repo.list_by_claim(claim_a.id, direction="outgoing")
        assert len(outgoing) >= 1
        assert all(r.source_claim_id == claim_a.id for r in outgoing)

        outgoing_b = await repo.list_by_claim(claim_b.id, direction="outgoing")
        assert len(outgoing_b) == 0

    async def test_list_by_claim_incoming(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = ReferenceRepository(db_session)
        ref = Reference(
            **make_reference(
                source_uri=f"claim:{claim_a.id}",
                target_uri=f"claim:{claim_b.id}",
                created_by=agent.id,
                role="evidence",
                source_claim_id=claim_a.id,
                target_claim_id=claim_b.id,
            )
        )
        await repo.create(ref)

        incoming = await repo.list_by_claim(claim_b.id, direction="incoming")
        assert len(incoming) >= 1
        assert all(r.target_claim_id == claim_b.id for r in incoming)


@needs_db
class TestListByRole:
    async def test_list_by_role(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = ReferenceRepository(db_session)
        ref1 = Reference(
            **make_reference(
                source_uri=f"claim:{claim_a.id}",
                target_uri=f"claim:{claim_b.id}",
                created_by=agent.id,
                role="evidence",
                source_claim_id=claim_a.id,
                target_claim_id=claim_b.id,
            )
        )
        ref2 = Reference(
            **make_reference(
                source_uri=f"claim:{claim_b.id}",
                target_uri=f"claim:{claim_a.id}",
                created_by=agent.id,
                role="derives_from",
                source_claim_id=claim_b.id,
                target_claim_id=claim_a.id,
            )
        )
        await repo.create(ref1)
        await repo.create(ref2)

        evidence = await repo.list_by_role("evidence")
        assert len(evidence) >= 1
        assert all(r.role == "evidence" for r in evidence)

        derives = await repo.list_by_role("derives_from")
        assert len(derives) >= 1
        assert all(r.role == "derives_from" for r in derives)


@needs_db
class TestListByUri:
    async def test_list_by_source_uri(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = ReferenceRepository(db_session)
        uri = f"claim:{claim_a.id}"
        ref = Reference(
            **make_reference(
                source_uri=uri,
                target_uri=f"claim:{claim_b.id}",
                created_by=agent.id,
                source_claim_id=claim_a.id,
                target_claim_id=claim_b.id,
            )
        )
        await repo.create(ref)

        results = await repo.list_by_source_uri(uri)
        assert len(results) >= 1
        assert all(r.source_uri == uri for r in results)

    async def test_list_by_target_uri(self, db_session: AsyncSession) -> None:
        agent, _ns, claim_a, claim_b = await _setup_claims(db_session)

        repo = ReferenceRepository(db_session)
        uri = f"claim:{claim_b.id}"
        ref = Reference(
            **make_reference(
                source_uri=f"claim:{claim_a.id}",
                target_uri=uri,
                created_by=agent.id,
                source_claim_id=claim_a.id,
                target_claim_id=claim_b.id,
            )
        )
        await repo.create(ref)

        results = await repo.list_by_target_uri(uri)
        assert len(results) >= 1
        assert all(r.target_uri == uri for r in results)
