# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from fastapi import APIRouter

from phiacta.api.agents import router as agents_router
from phiacta.api.auth import router as auth_router
from phiacta.api.bundles import router as bundles_router
from phiacta.api.claims import router as claims_router
from phiacta.api.extensions import router as extensions_router
from phiacta.api.namespaces import router as namespaces_router
from phiacta.api.relations import router as relations_router
from phiacta.api.reviews import router as reviews_router
from phiacta.api.search import router as search_router
from phiacta.api.sources import router as sources_router

v1_router = APIRouter()
v1_router.include_router(auth_router)
v1_router.include_router(claims_router)
v1_router.include_router(reviews_router)
v1_router.include_router(agents_router)
v1_router.include_router(relations_router)
v1_router.include_router(sources_router)
v1_router.include_router(bundles_router)
v1_router.include_router(namespaces_router)
v1_router.include_router(search_router)
v1_router.include_router(extensions_router)
