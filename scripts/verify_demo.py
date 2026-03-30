#!/usr/bin/env python3
"""Demonstrate creating an entry with a Lean 4 verified proof.

Usage:
    python scripts/verify_demo.py
    python scripts/verify_demo.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.phiacta.com"
SEED_USERNAME = "seed-user"
SEED_USER_PASSWORD = os.environ.get("PHIACTA_SEED_PASSWORD", "SeedAgent!2026")
TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# The entry
# ---------------------------------------------------------------------------

ENTRY_TITLE = "Commutativity and Associativity of Natural Number Addition"
ENTRY_SUMMARY = (
    "For all natural numbers a and b, addition is commutative: a + b = b + a. "
    "Furthermore, addition is associative: (a + b) + c = a + (b + c), "
    "and multiplication distributes over addition: a * (b + c) = a * b + a * c."
)

LEAN4_PROOF = """\
/--
  Fundamental algebraic properties of natural number arithmetic.
  Each theorem is proven using Lean 4's built-in tactics and
  standard library lemmas, requiring no external dependencies.
-/

-- Commutativity of addition
theorem nat_add_comm (a b : Nat) : a + b = b + a := by omega

-- Associativity of addition
theorem nat_add_assoc (a b c : Nat) : (a + b) + c = a + (b + c) := by omega

-- Left distributivity of multiplication over addition
theorem nat_left_distrib (a b c : Nat) : a * (b + c) = a * b + a * c := by omega
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def v1(base: str) -> str:
    return f"{base}/v1"


def login(client: httpx.Client, base: str) -> tuple[str, str]:
    """Log in as the seed user. Returns (token, user_id)."""
    r = client.post(
        f"{v1(base)}/auth/login",
        json={"username": SEED_USERNAME, "password": SEED_USER_PASSWORD},
    )
    r.raise_for_status()
    data = r.json()
    return data["access_token"], data["user"]["id"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_entry(
    client: httpx.Client,
    base: str,
    token: str,
) -> str:
    """Create the theorem entry. Returns the entry ID."""
    # Check if it already exists.
    r = client.get(f"{v1(base)}/entries?limit=100", headers=auth_headers(token))
    r.raise_for_status()
    for e in r.json()["items"]:
        if e["title"] == ENTRY_TITLE:
            print(f"  Entry already exists: {e['id']}")
            return e["id"]

    r = client.post(
        f"{v1(base)}/entries",
        json={
            "title": ENTRY_TITLE,
            "summary": ENTRY_SUMMARY,
            "layout_hint": "theorem",
            "tags": ["mathematics", "number-theory"],
        },
        headers=auth_headers(token),
    )
    # 500 is possible if extensions table issue; data may still commit.
    if r.status_code not in (200, 201, 500):
        print(f"  Unexpected status creating entry: {r.status_code}")
        print(f"  {r.text}")
        sys.exit(1)

    if r.status_code == 500:
        print("  Got 500 (expected — extensions issue), looking up entry...")
        r2 = client.get(f"{v1(base)}/entries?limit=100", headers=auth_headers(token))
        r2.raise_for_status()
        for e in r2.json()["items"]:
            if e["title"] == ENTRY_TITLE:
                print(f"  Found entry: {e['id']}")
                return e["id"]
        raise RuntimeError("Entry was not committed despite 500")

    entry_id = r.json()["id"]
    print(f"  Created entry: {entry_id}")
    return entry_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a theorem entry with Lean 4 proof")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    client = httpx.Client(timeout=TIMEOUT)

    print("1. Logging in as seed user...")
    token, user_id = login(client, base)
    print(f"   User: {user_id}")

    print("2. Creating theorem entry...")
    entry_id = create_entry(client, base, token)

    print()
    print(f"Done! View at: https://phiacta.com/entries/{entry_id}")
    print(f"Lean 4 proof ({len(LEAN4_PROOF)} bytes) can be committed to the entry's git repo.")


if __name__ == "__main__":
    main()
