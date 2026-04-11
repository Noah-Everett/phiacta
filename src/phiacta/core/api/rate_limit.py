# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Shared rate limiter instance for all API endpoints."""

from __future__ import annotations

from starlette.requests import Request
from slowapi import Limiter


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP behind Cloudflare Tunnel or other proxies.

    Priority:
    1. CF-Connecting-IP — set by Cloudflare, non-spoofable behind their tunnel.
    2. X-Forwarded-For — leftmost IP (original client).
    3. request.client.host — direct TCP peer (dev/local).
    """
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()

    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


limiter = Limiter(key_func=_get_client_ip)
