# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from phiacta.layers.base import Layer
from phiacta.layers.graph.models import GraphEdgeType
from phiacta.layers.graph.routes import create_graph_router

# The 15 seed edge types from the original schema design.
_SEED_EDGE_TYPES = """
INSERT INTO graph_edge_types (name, description, inverse_name, is_transitive, is_symmetric, category)
VALUES
    -- Evidential
    ('supports',        'Source provides evidence for target',                    'supported_by',      false, false, 'evidential'),
    ('contradicts',     'Source provides evidence against target',                'contradicts',       false, true,  'evidential'),
    ('corroborates',    'Independent evidence for the same target',               'corroborated_by',   false, false, 'evidential'),
    -- Logical
    ('depends_on',      'Source requires target to hold',                         'depended_on_by',    true,  false, 'logical'),
    ('assumes',         'Source takes target as given without proof',             'assumed_by',        true,  false, 'logical'),
    ('derives_from',    'Source is logically derived from target',                'derives',           true,  false, 'logical'),
    ('implies',         'If source holds, target must hold',                      'implied_by',        true,  false, 'logical'),
    ('equivalent_to',   'Source and target are logically equivalent',             'equivalent_to',     true,  true,  'logical'),
    -- Structural
    ('generalizes',     'Source is a more general form of target',                'specializes',       true,  false, 'structural'),
    ('refines',         'Source is a more precise version of target',             'refined_by',        false, false, 'structural'),
    ('part_of',         'Source is a component of target',                        'has_part',          true,  false, 'structural'),
    ('instantiates',    'Source is a concrete instance of target pattern',        'instantiated_by',   false, false, 'structural'),
    -- Editorial
    ('supersedes',      'Source replaces target (versioning)',                    'superseded_by',     true,  false, 'editorial'),
    ('related_to',      'Weak/untyped association',                              'related_to',        false, true,  'editorial'),
    ('responds_to',     'Source is a response/reply to target',                  'responded_to_by',   false, false, 'editorial')
ON CONFLICT (name) DO NOTHING
"""


class GraphLayer(Layer):
    """Interprets core relations as a typed, semantic knowledge graph.

    Owns the graph_edge_types table with formal properties (transitive,
    symmetric, inverse). Provides graph traversal and neighbor queries.
    """

    @property
    def name(self) -> str:
        return "graph"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Typed knowledge graph with semantic edge properties and traversal"

    def router(self) -> APIRouter:
        return create_graph_router()

    async def setup(self, engine: AsyncEngine) -> None:
        """Create graph_edge_types table and seed the 15 default types."""
        async with engine.begin() as conn:
            await conn.run_sync(GraphEdgeType.__table__.create, checkfirst=True)  # type: ignore[attr-defined]
            await conn.execute(text(_SEED_EDGE_TYPES))
