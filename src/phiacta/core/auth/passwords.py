# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

from __future__ import annotations

import asyncio

import bcrypt


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt (synchronous, CPU-blocking)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash (synchronous, CPU-blocking)."""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


async def hash_password_async(password: str) -> str:
    """Hash a plaintext password without blocking the event loop."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    """Verify a plaintext password without blocking the event loop."""
    return await asyncio.to_thread(verify_password, password, password_hash)
