# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from fastapi import APIRouter

from phiacta.api.agents import router as agents_router
from phiacta.api.auth import router as auth_router
from phiacta.api.entries import router as entries_router
from phiacta.api.entry_files import router as entry_files_router
from phiacta.api.entry_history import router as entry_history_router
from phiacta.api.entry_refs import router as entry_refs_router

v1_router = APIRouter()
v1_router.include_router(auth_router)
v1_router.include_router(entries_router)
v1_router.include_router(entry_files_router)
v1_router.include_router(entry_history_router)
v1_router.include_router(agents_router)
v1_router.include_router(entry_refs_router)
