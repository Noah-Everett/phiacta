# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import uuid4

from phiacta.models.agent import Agent
from phiacta.models.artifact import Artifact
from phiacta.models.base import Base, TimestampMixin, UUIDMixin
from phiacta.models.bundle import Bundle
from phiacta.models.claim import Claim
from phiacta.models.interaction import Interaction
from phiacta.models.layer_registry import LayerRecord
from phiacta.models.outbox import Outbox
from phiacta.models.reference import Reference, ReferenceRole


class TestClaimDefaults:
    def test_claim_defaults(self) -> None:
        ns_id = uuid4()
        agent_id = uuid4()
        claim = Claim(
            title="Test claim",
            claim_type="assertion",
            namespace_id=ns_id,
            created_by=agent_id,
            attrs={},
        )
        assert claim.title == "Test claim"
        assert claim.claim_type == "assertion"
        assert claim.namespace_id == ns_id
        assert claim.created_by == agent_id
        assert claim.content_cache is None
        assert claim.forgejo_repo_id is None
        assert claim.current_head_sha is None
        assert claim.embedding is None
        assert claim.search_tsv is None
        # Column-level defaults applied at flush
        status_col = Claim.__table__.c["status"]
        assert status_col.default is not None
        assert status_col.default.arg == "active"
        repo_status_col = Claim.__table__.c["repo_status"]
        assert repo_status_col.default is not None
        assert repo_status_col.default.arg == "provisioning"

    def test_claim_type_accepts_arbitrary_strings(self) -> None:
        """claim_type is freeform text -- no CHECK constraint in core."""
        for ct in ["assertion", "theorem", "clinical_finding", "custom_type"]:
            claim = Claim(
                title=f"Claim of type {ct}",
                claim_type=ct,
                namespace_id=uuid4(),
                created_by=uuid4(),
                attrs={},
            )
            assert claim.claim_type == ct


class TestInteractionDefaults:
    def test_vote_interaction(self) -> None:
        interaction = Interaction(
            claim_id=uuid4(),
            author_id=uuid4(),
            kind="vote",
            signal="agree",
            confidence=0.9,
            attrs={},
        )
        assert interaction.kind == "vote"
        assert interaction.signal == "agree"
        assert interaction.confidence == 0.9
        assert interaction.body is None

    def test_review_interaction(self) -> None:
        interaction = Interaction(
            claim_id=uuid4(),
            author_id=uuid4(),
            kind="review",
            signal="disagree",
            confidence=0.7,
            body="This claim has issues",
            attrs={},
        )
        assert interaction.kind == "review"
        assert interaction.body == "This claim has issues"


class TestReferenceDefaults:
    def test_reference_fields(self) -> None:
        claim_a = uuid4()
        claim_b = uuid4()
        ref = Reference(
            source_uri=f"claim:{claim_a}",
            target_uri=f"claim:{claim_b}",
            role="evidence",
            created_by=uuid4(),
            source_type="claim",
            target_type="claim",
            source_claim_id=claim_a,
            target_claim_id=claim_b,
        )
        assert ref.role == "evidence"
        assert ref.source_type == "claim"
        assert ref.target_type == "claim"

    def test_reference_role_enum(self) -> None:
        assert ReferenceRole.EVIDENCE == "evidence"
        assert ReferenceRole.DERIVES_FROM == "derives_from"
        assert ReferenceRole.SUPERSEDES == "supersedes"


class TestOutboxDefaults:
    def test_outbox_fields(self) -> None:
        entry = Outbox(
            operation="create_repo",
            payload={"claim_id": str(uuid4())},
        )
        assert entry.operation == "create_repo"
        assert entry.last_error is None
        assert entry.processed_at is None
        # Column-level defaults
        status_col = Outbox.__table__.c["status"]
        assert status_col.default.arg == "pending"
        attempts_col = Outbox.__table__.c["attempts"]
        assert attempts_col.default.arg == 0
        max_attempts_col = Outbox.__table__.c["max_attempts"]
        assert max_attempts_col.default.arg == 5


class TestLayerRecordDefaults:
    def test_layer_record_fields(self) -> None:
        lr = LayerRecord(
            name="graph",
            version="0.1.0",
            config={},
        )
        assert lr.name == "graph"
        assert lr.version == "0.1.0"
        enabled_col = LayerRecord.__table__.c["enabled"]
        assert enabled_col.default is not None
        assert enabled_col.default.arg is True


class TestAgentDefaults:
    def test_agent_defaults(self) -> None:
        agent = Agent(
            agent_type="human",
            name="Researcher",
            attrs={},
        )
        assert agent.agent_type == "human"
        assert agent.name == "Researcher"
        assert agent.external_id is None
        assert agent.api_key_hash is None
        trust_col = Agent.__table__.c["trust_score"]
        assert trust_col.default is not None
        assert trust_col.default.arg == 1.0


class TestBundleDefaults:
    def test_bundle_defaults(self) -> None:
        agent_id = uuid4()
        bundle = Bundle(
            idempotency_key="test-key-123",
            submitted_by=agent_id,
            extension_id="paper-ingestion",
            attrs={},
        )
        assert bundle.idempotency_key == "test-key-123"
        assert bundle.submitted_by == agent_id
        status_col = Bundle.__table__.c["status"]
        assert status_col.default is not None
        assert status_col.default.arg == "accepted"


class TestArtifactDefaults:
    def test_artifact_defaults(self) -> None:
        artifact = Artifact(
            artifact_type="figure",
            attrs={},
        )
        assert artifact.artifact_type == "figure"
        assert artifact.bundle_id is None


class TestUUIDMixin:
    def test_uuid_mixin_generates_uuid(self) -> None:
        agent = Agent(
            agent_type="ai",
            name="AI Agent",
            attrs={},
        )
        assert agent.id is not None or hasattr(Agent, "id")
        col = Agent.__table__.c["id"]
        assert col.primary_key is True
        assert col.default is not None


class TestTimestampMixin:
    def test_timestamp_mixin_fields_exist(self) -> None:
        table = Claim.__table__
        assert "created_at" in table.c
        assert "updated_at" in table.c
        assert table.c["created_at"].server_default is not None
        assert table.c["updated_at"].server_default is not None

    def test_mixin_classes_have_attributes(self) -> None:
        assert hasattr(UUIDMixin, "id")
        assert hasattr(TimestampMixin, "created_at")
        assert hasattr(TimestampMixin, "updated_at")

    def test_base_is_declarative(self) -> None:
        assert hasattr(Base, "metadata")
        assert hasattr(Base, "registry")
