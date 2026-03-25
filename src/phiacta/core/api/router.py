# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from fastapi import APIRouter

from phiacta.core.api.activity import router as activity_router
from phiacta.core.api.auth import router as auth_router
from phiacta.core.api.entries import router as entries_router
from phiacta.core.api.entry_edits import router as entry_edits_router
from phiacta.core.api.entry_files import router as entry_files_router
from phiacta.core.api.entry_history import router as entry_history_router
from phiacta.core.api.entry_issues import router as entry_issues_router
from phiacta.core.api.plugins import router as plugins_router
from phiacta.core.api.users import router as users_router

v1_router = APIRouter()
v1_router.include_router(activity_router)
v1_router.include_router(auth_router)
v1_router.include_router(entries_router)
v1_router.include_router(entry_edits_router)
v1_router.include_router(entry_files_router)
v1_router.include_router(entry_history_router)
v1_router.include_router(entry_issues_router)
v1_router.include_router(plugins_router)
v1_router.include_router(users_router)
