# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 NewPublishing Contributors

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def create_confidence_router() -> APIRouter:
    """Create the confidence layer's API router."""
    router = APIRouter()

    @router.get("/claims/{claim_id}/status")
    async def get_epistemic_status(claim_id: str) -> dict[str, Any]:
        """Get the epistemic status and confidence scores for a claim."""
        # TODO: query claims_with_confidence view
        return {"claim_id": claim_id, "epistemic_status": "unverified"}

    @router.get("/claims")
    async def list_claims_with_confidence() -> list[dict[str, Any]]:
        """List claims with their aggregated confidence scores."""
        # TODO: query claims_with_confidence view with filters
        return []

    return router
