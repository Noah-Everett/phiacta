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
    COUNT(i.id) FILTER (WHERE i.signal IS NOT NULL) AS signal_count,
    COUNT(i.id) AS interaction_count,
    SUM(i.weight * i.confidence) FILTER (WHERE i.signal = 'agree')
        / NULLIF(SUM(i.weight) FILTER (WHERE i.signal = 'agree'), 0)
        AS weighted_agree_confidence,
    COUNT(*) FILTER (WHERE i.signal = 'agree') AS agree_count,
    COUNT(*) FILTER (WHERE i.signal = 'disagree') AS disagree_count,
    COUNT(*) FILTER (WHERE i.signal = 'neutral') AS neutral_count,
    COUNT(*) FILTER (WHERE i.kind = 'issue'
        AND (i.attrs->>'issue_status') IN ('open', 'reopened')) AS open_issue_count,
    COUNT(*) FILTER (WHERE i.kind = 'suggestion'
        AND (i.attrs->>'suggestion_status') = 'pending') AS pending_suggestion_count,
    CASE
        WHEN COUNT(i.id) FILTER (WHERE i.signal IS NOT NULL) = 0 THEN 'unverified'
        WHEN COUNT(*) FILTER (WHERE i.signal = 'disagree') > 0
             AND COUNT(*) FILTER (WHERE i.signal = 'agree') > 0 THEN 'disputed'
        WHEN c.formal_content IS NOT NULL
             AND COUNT(*) FILTER (WHERE i.signal = 'agree') > 0 THEN 'formally_verified'
        WHEN SUM(i.weight * i.confidence) FILTER (WHERE i.signal = 'agree')
                 / NULLIF(SUM(i.weight) FILTER (WHERE i.signal = 'agree'), 0) > 0.7
             AND COUNT(*) FILTER (WHERE i.signal = 'agree')
                 > COUNT(*) FILTER (WHERE i.signal = 'disagree') THEN 'endorsed'
        ELSE 'under_review'
    END AS epistemic_status
FROM claims c
LEFT JOIN interactions i ON i.claim_id = c.id AND i.deleted_at IS NULL
GROUP BY c.id
"""


class ConfidenceLayer(Layer):
    """Computes epistemic status and confidence scores from interactions.

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
        return "Epistemic status scoring from community interactions"

    def router(self) -> APIRouter:
        return create_confidence_router()

    async def setup(self, engine: AsyncEngine) -> None:
        """Create the claims_with_confidence view."""
        async with engine.begin() as conn:
            await conn.execute(text(_CLAIMS_WITH_CONFIDENCE_VIEW))
