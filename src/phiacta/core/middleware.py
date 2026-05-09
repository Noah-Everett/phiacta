# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Custom ASGI middleware."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject non-multipart requests whose Content-Length exceeds *max_bytes*.

    Multipart (file uploads) is excluded — those have their own limits
    enforced at the service layer via ``max_file_size_bytes``.
    """

    def __init__(self, app, max_bytes: int = 1 * 1024 * 1024) -> None:  # noqa: D107
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001,ANN201
        content_type = request.headers.get("content-type", "")

        if "multipart" not in content_type:
            content_length = request.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > self.max_bytes:
                        return JSONResponse(
                            status_code=413,
                            content={
                                "detail": f"Request body too large. Maximum: {self.max_bytes} bytes",
                            },
                        )
                except ValueError:
                    pass

        return await call_next(request)
