# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Personal Access Token utilities.

Pure functions for token generation, hashing, prefix extraction, and
verification.  These are used by the auth dependency and the token
management endpoints.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PAT_PREFIX = "pat_"
PAT_RANDOM_BYTES = 32  # secrets.token_urlsafe(32) → 43 chars
PAT_KEY_PREFIX_LEN = 8  # first 8 chars of the random portion


def generate_pat() -> str:
    """Generate a new PAT: ``pat_`` + 43 URL-safe random characters."""
    return PAT_PREFIX + secrets.token_urlsafe(PAT_RANDOM_BYTES)


def extract_pat_prefix(token: str) -> str:
    """Extract the 8-char lookup prefix (chars 4–12 of the full token)."""
    return token[len(PAT_PREFIX) : len(PAT_PREFIX) + PAT_KEY_PREFIX_LEN]


def hash_pat(token: str) -> str:
    """Return the SHA-256 hex digest of the full token string."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_pat(token: str, key_hash: str) -> bool:
    """Timing-safe comparison of a token's hash against a stored hash."""
    computed = hash_pat(token)
    return hmac.compare_digest(computed, key_hash)


def is_pat(token: str) -> bool:
    """Check whether a string looks like a PAT (starts with ``pat_``)."""
    return token.startswith(PAT_PREFIX)
