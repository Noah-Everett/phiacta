# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from phiacta.layers.base import Layer
from phiacta.layers.confidence.routes import create_confidence_router

_CLAIMS_WITH_CONFIDENCE_VIEW = """
CREATE OR REPLACE VIEW claims_with_confidence AS
SELECT
    c.id,
    c.lineage_id,
    c.content,
    c.claim_type,
    c.status,
    c.version,
    COUNT(r.id) AS review_count,
    AVG(r.confidence) FILTER (WHERE r.verdict = 'endorse') AS avg_endorsement_confidence,
    COUNT(*) FILTER (WHERE r.verdict = 'endorse') AS endorsement_count,
    COUNT(*) FILTER (WHERE r.verdict = 'dispute') AS dispute_count,
    CASE
        WHEN COUNT(r.id) = 0 THEN 'unverified'
        WHEN COUNT(*) FILTER (WHERE r.verdict = 'dispute') > 0
             AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > 0 THEN 'disputed'
        WHEN c.formal_content IS NOT NULL
             AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > 0 THEN 'formally_verified'
        WHEN AVG(r.confidence) FILTER (WHERE r.verdict = 'endorse') > 0.7
             AND COUNT(*) FILTER (WHERE r.verdict = 'endorse') > COUNT(*) FILTER (WHERE r.verdict = 'dispute')
             THEN 'endorsed'
        ELSE 'under_review'
    END AS epistemic_status
FROM claims c
LEFT JOIN reviews r ON r.claim_id = c.id
GROUP BY c.id
"""


class ConfidenceLayer(Layer):
    """Computes epistemic status and confidence scores from reviews.

    Owns the claims_with_confidence view. Different communities can
    swap this layer for alternative confidence/scoring models.
    """

    @property
    def name(self) -> str:
        return "confidence"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def description(self) -> str:
        return "Epistemic status scoring from community reviews"

    def router(self) -> APIRouter:
        return create_confidence_router()

    async def setup(self, engine: AsyncEngine) -> None:
        """Create the claims_with_confidence view."""
        async with engine.begin() as conn:
            await conn.execute(text(_CLAIMS_WITH_CONFIDENCE_VIEW))
