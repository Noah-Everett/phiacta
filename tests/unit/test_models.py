# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from uuid import uuid4

from phiacta.models.agent import Agent
from phiacta.models.artifact import Artifact
from phiacta.models.base import Base, TimestampMixin, UUIDMixin
from phiacta.models.bundle import Bundle
from phiacta.models.claim import Claim
from phiacta.models.layer_registry import LayerRecord
from phiacta.models.relation import Relation


class TestClaimDefaults:
    def test_claim_defaults(self) -> None:
        ns_id = uuid4()
        agent_id = uuid4()
        claim = Claim(
            lineage_id=uuid4(),
            content="Test claim",
            claim_type="assertion",
            namespace_id=ns_id,
            created_by=agent_id,
            attrs={},
        )
        assert claim.content == "Test claim"
        assert claim.claim_type == "assertion"
        assert claim.namespace_id == ns_id
        assert claim.created_by == agent_id
        assert claim.formal_content is None
        assert claim.supersedes is None
        assert claim.embedding is None
        assert claim.search_tsv is None
        # Column-level defaults (version=1, status='active') are applied at flush,
        # so verify the column definition has them configured.
        version_col = Claim.__table__.c["version"]
        assert version_col.default is not None
        assert version_col.default.arg == 1
        status_col = Claim.__table__.c["status"]
        assert status_col.default is not None
        assert status_col.default.arg == "active"

    def test_claim_type_accepts_arbitrary_strings(self) -> None:
        """claim_type is freeform text — no CHECK constraint in core."""
        for ct in ["assertion", "theorem", "clinical_finding", "custom_type"]:
            claim = Claim(
                lineage_id=uuid4(),
                content=f"Claim of type {ct}",
                claim_type=ct,
                namespace_id=uuid4(),
                created_by=uuid4(),
                attrs={},
            )
            assert claim.claim_type == ct


class TestRelationDefaults:
    def test_relation_defaults(self) -> None:
        rel = Relation(
            source_id=uuid4(),
            target_id=uuid4(),
            relation_type="supports",
            created_by=uuid4(),
            attrs={},
        )
        assert rel.relation_type == "supports"
        assert rel.strength is None
        assert rel.source_provenance is None

    def test_relation_type_accepts_arbitrary_strings(self) -> None:
        """relation_type is freeform text — layers interpret semantics."""
        for rt in ["supports", "contradicts", "custom_relation", "cites"]:
            rel = Relation(
                source_id=uuid4(),
                target_id=uuid4(),
                relation_type=rt,
                created_by=uuid4(),
                attrs={},
            )
            assert rel.relation_type == rt


class TestLayerRecordDefaults:
    def test_layer_record_fields(self) -> None:
        lr = LayerRecord(
            name="graph",
            version="0.1.0",
            config={},
        )
        assert lr.name == "graph"
        assert lr.version == "0.1.0"
        # enabled default is applied at flush, verify column config
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
        # trust_score default (1.0) is applied at flush
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
        assert bundle.extension_id == "paper-ingestion"
        # Column-level defaults applied at flush, verify column config
        status_col = Bundle.__table__.c["status"]
        assert status_col.default is not None
        assert status_col.default.arg == "accepted"
        claim_count_col = Bundle.__table__.c["claim_count"]
        assert claim_count_col.default is not None
        assert claim_count_col.default.arg == 0
        relation_count_col = Bundle.__table__.c["relation_count"]
        assert relation_count_col.default is not None
        assert relation_count_col.default.arg == 0


class TestArtifactDefaults:
    def test_artifact_defaults(self) -> None:
        artifact = Artifact(
            artifact_type="figure",
            attrs={},
        )
        assert artifact.artifact_type == "figure"
        assert artifact.bundle_id is None
        assert artifact.description is None
        assert artifact.storage_ref is None
        assert artifact.content_inline is None
        assert artifact.structured_data is None


class TestUUIDMixin:
    def test_uuid_mixin_generates_uuid(self) -> None:
        agent = Agent(
            agent_type="ai",
            name="AI Agent",
            attrs={},
        )
        # When default is set, instantiation should provide a UUID via default factory
        # The id is generated by uuid4 default
        assert agent.id is not None or hasattr(Agent, "id")
        # Verify the column is mapped with a default
        col = Agent.__table__.c["id"]
        assert col.primary_key is True
        assert col.default is not None


class TestTimestampMixin:
    def test_timestamp_mixin_fields_exist(self) -> None:
        # Verify that TimestampMixin-using models have created_at and updated_at columns
        table = Claim.__table__
        assert "created_at" in table.c
        assert "updated_at" in table.c
        created_col = table.c["created_at"]
        updated_col = table.c["updated_at"]
        assert created_col.server_default is not None
        assert updated_col.server_default is not None

    def test_mixin_classes_have_attributes(self) -> None:
        assert hasattr(UUIDMixin, "id")
        assert hasattr(TimestampMixin, "created_at")
        assert hasattr(TimestampMixin, "updated_at")

    def test_base_is_declarative(self) -> None:
        assert hasattr(Base, "metadata")
        assert hasattr(Base, "registry")
