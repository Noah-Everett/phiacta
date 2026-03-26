# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors

"""Unit tests for PAT utility functions (PHI-119).

Tests the pure functions for token generation, hashing, prefix extraction,
and verification — no database or HTTP involved.
"""

from __future__ import annotations

import hashlib
import re

from phiacta.core.auth.pat import (
    extract_pat_prefix,
    generate_pat,
    hash_pat,
    is_pat,
    verify_pat,
)


class TestGeneratePat:
    """Tests for generate_pat() — creates a new PAT string."""

    def test_starts_with_pat_prefix(self) -> None:
        """Generated PAT starts with 'pat_'."""
        token = generate_pat()
        assert token.startswith("pat_")

    def test_correct_total_length(self) -> None:
        """Generated PAT has total length of ~47 chars (4 prefix + 43 random)."""
        token = generate_pat()
        # pat_ (4 chars) + token_urlsafe(32) which is 43 chars
        assert len(token) == 47

    def test_random_portion_is_url_safe(self) -> None:
        """The random portion contains only URL-safe base64 characters."""
        token = generate_pat()
        random_part = token[4:]
        # URL-safe base64 uses [A-Za-z0-9_-]
        assert re.match(r'^[A-Za-z0-9_-]+$', random_part), (
            f"Random portion contains non-URL-safe chars: {random_part!r}"
        )

    def test_generates_unique_tokens(self) -> None:
        """Multiple calls produce distinct tokens."""
        tokens = {generate_pat() for _ in range(100)}
        assert len(tokens) == 100

    def test_return_type_is_string(self) -> None:
        """Returns a plain string (not bytes)."""
        token = generate_pat()
        assert isinstance(token, str)


class TestExtractPatPrefix:
    """Tests for extract_pat_prefix() — extracts the 8-char lookup prefix."""

    def test_extracts_first_8_chars_after_pat_(self) -> None:
        """Prefix is chars [4:12] of the full token (first 8 of random portion)."""
        token = "pat_ABCDEFGH1234567890abcdefghijklmnopqrstuvw"
        prefix = extract_pat_prefix(token)
        assert prefix == "ABCDEFGH"

    def test_prefix_length_is_8(self) -> None:
        """Prefix is always 8 characters."""
        token = generate_pat()
        prefix = extract_pat_prefix(token)
        assert len(prefix) == 8

    def test_prefix_matches_token_chars_4_to_12(self) -> None:
        """Prefix matches token[4:12] exactly."""
        token = generate_pat()
        prefix = extract_pat_prefix(token)
        assert prefix == token[4:12]

    def test_prefix_from_known_token(self) -> None:
        """Known input produces known output."""
        token = "pat_XYZ12345restofthetoken0123456789abcdefghij"
        prefix = extract_pat_prefix(token)
        assert prefix == "XYZ12345"


class TestHashPat:
    """Tests for hash_pat() — SHA-256 hash of the full token."""

    def test_returns_64_char_hex_string(self) -> None:
        """SHA-256 hex digest is exactly 64 characters."""
        token = generate_pat()
        hashed = hash_pat(token)
        assert len(hashed) == 64

    def test_is_lowercase_hex(self) -> None:
        """Hash is a lowercase hex string."""
        token = generate_pat()
        hashed = hash_pat(token)
        assert re.match(r'^[0-9a-f]{64}$', hashed)

    def test_consistent_hashing(self) -> None:
        """Same token always produces the same hash."""
        token = generate_pat()
        hash1 = hash_pat(token)
        hash2 = hash_pat(token)
        assert hash1 == hash2

    def test_different_tokens_produce_different_hashes(self) -> None:
        """Different tokens produce different hashes."""
        token1 = generate_pat()
        token2 = generate_pat()
        assert hash_pat(token1) != hash_pat(token2)

    def test_matches_python_sha256(self) -> None:
        """Hash matches Python's standard hashlib SHA-256."""
        token = "pat_test123456789abcdefghijklmnopqrstuvwxyz_"
        expected = hashlib.sha256(token.encode()).hexdigest()
        assert hash_pat(token) == expected


class TestVerifyPat:
    """Tests for verify_pat() — timing-safe hash comparison."""

    def test_correct_key_returns_true(self) -> None:
        """Verifying with the correct token returns True."""
        token = generate_pat()
        hashed = hash_pat(token)
        assert verify_pat(token, hashed) is True

    def test_wrong_key_returns_false(self) -> None:
        """Verifying with a wrong token returns False."""
        token = generate_pat()
        hashed = hash_pat(token)
        wrong_token = generate_pat()
        assert verify_pat(wrong_token, hashed) is False

    def test_empty_token_returns_false(self) -> None:
        """Verifying with an empty string returns False."""
        token = generate_pat()
        hashed = hash_pat(token)
        assert verify_pat("", hashed) is False

    def test_similar_token_returns_false(self) -> None:
        """Verifying with a nearly-identical token returns False."""
        token = generate_pat()
        hashed = hash_pat(token)
        # Flip last character
        if token[-1] == "a":
            wrong = token[:-1] + "b"
        else:
            wrong = token[:-1] + "a"
        assert verify_pat(wrong, hashed) is False

    def test_returns_boolean(self) -> None:
        """Return type is strictly bool."""
        token = generate_pat()
        hashed = hash_pat(token)
        result = verify_pat(token, hashed)
        assert isinstance(result, bool)
        assert result is True


class TestIsPat:
    """Tests for is_pat() — checks if a string looks like a PAT."""

    def test_valid_pat_returns_true(self) -> None:
        """A properly formatted PAT returns True."""
        token = generate_pat()
        assert is_pat(token) is True

    def test_jwt_token_returns_false(self) -> None:
        """A JWT-like token (starts with eyJ) returns False."""
        assert is_pat("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.fakesig") is False

    def test_empty_string_returns_false(self) -> None:
        """Empty string returns False."""
        assert is_pat("") is False

    def test_pat_prefix_only_returns_true(self) -> None:
        """'pat_' with random chars is recognized."""
        assert is_pat("pat_ABCDEFGHIJKLMNOP") is True

    def test_non_pat_prefix_returns_false(self) -> None:
        """A string not starting with pat_ returns False."""
        assert is_pat("token_abc123") is False
        assert is_pat("PAT_abc123") is False
        assert is_pat("pat-abc123") is False

    def test_none_like_inputs(self) -> None:
        """Handles edge case inputs gracefully."""
        assert is_pat("pat") is False
        assert is_pat("pa") is False
        assert is_pat("p") is False
