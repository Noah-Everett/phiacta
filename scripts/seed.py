#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors
"""Seed the Phiacta database with foundational science entries via the REST API.

Usage:
    python scripts/seed.py                           # defaults to https://phiacta.com
    python scripts/seed.py --base-url http://localhost:8000
    PHIACTA_SEED_PASSWORD=supersecret python scripts/seed.py
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
SEED_AGENT_HANDLE = "seed-agent"
SEED_AGENT_EMAIL = "seed@phiacta.com"
SEED_AGENT_PASSWORD = os.environ.get("PHIACTA_SEED_PASSWORD", "SeedAgent!2026")

TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def api(base: str) -> str:
    return f"{base}/v1"


def post(
    client: httpx.Client,
    url: str,
    json: dict,
    *,
    token: str | None = None,
    tolerate_500: bool = False,
) -> dict | None:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = client.post(url, json=json, headers=headers, timeout=TIMEOUT)
    if r.status_code >= 400:
        if tolerate_500 and r.status_code == 500:
            print("  WARN: got 500 (data likely committed anyway)", file=sys.stderr)
            return None
        print(f"  ERROR {r.status_code}: {r.text[:200]}", file=sys.stderr)
        r.raise_for_status()
    return r.json()


def get(client: httpx.Client, url: str, *, token: str | None = None, params: dict | None = None) -> dict:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = client.get(url, headers=headers, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

# Entries: keyed for later reference linking
# layout_hint values: law, theorem, assertion, evidence, definition, hypothesis
ENTRIES = [
    # -- Classical Mechanics --
    {
        "key": "newton_1",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics"],
        "title": "Newton's First Law",
        "summary": "An object at rest stays at rest, and an object in motion stays in uniform motion, unless acted upon by a net external force.",
    },
    {
        "key": "newton_2",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics"],
        "title": "Newton's Second Law",
        "summary": "The acceleration of an object is directly proportional to the net force acting on it and inversely proportional to its mass. F = ma.",
    },
    {
        "key": "newton_3",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics"],
        "title": "Newton's Third Law",
        "summary": "For every action, there is an equal and opposite reaction.",
    },
    {
        "key": "conservation_energy",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics"],
        "title": "Law of Conservation of Energy",
        "summary": "Energy cannot be created or destroyed in an isolated system; it can only be transformed.",
    },
    {
        "key": "conservation_momentum",
        "layout_hint": "theorem",
        "tags": ["physics", "classical-mechanics"],
        "title": "Conservation of Linear Momentum",
        "summary": "In a closed system with no external forces, the total linear momentum is conserved.",
    },
    {
        "key": "universal_gravitation",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics"],
        "title": "Newton's Law of Universal Gravitation",
        "summary": "Every particle attracts every other particle with a force proportional to the product of their masses and inversely proportional to the square of the distance.",
    },
    # -- Thermodynamics --
    {
        "key": "thermo_0",
        "layout_hint": "law",
        "tags": ["physics", "thermodynamics"],
        "title": "Zeroth Law of Thermodynamics",
        "summary": "If two systems are each in thermal equilibrium with a third, they are in thermal equilibrium with each other.",
    },
    {
        "key": "thermo_1",
        "layout_hint": "law",
        "tags": ["physics", "thermodynamics"],
        "title": "First Law of Thermodynamics",
        "summary": "The change in internal energy of a closed system equals the heat added minus the work done.",
    },
    {
        "key": "thermo_2",
        "layout_hint": "law",
        "tags": ["physics", "thermodynamics"],
        "title": "Second Law of Thermodynamics",
        "summary": "The total entropy of an isolated system can only increase over time.",
    },
    {
        "key": "thermo_3",
        "layout_hint": "law",
        "tags": ["physics", "thermodynamics"],
        "title": "Third Law of Thermodynamics",
        "summary": "As temperature approaches absolute zero, entropy approaches a minimum value.",
    },
    # -- Electromagnetism --
    {
        "key": "maxwell_equations",
        "layout_hint": "law",
        "tags": ["physics", "electromagnetism"],
        "title": "Maxwell's Equations",
        "summary": "Four equations forming the foundation of classical electromagnetism.",
    },
    {
        "key": "coulombs_law",
        "layout_hint": "law",
        "tags": ["physics", "electromagnetism"],
        "title": "Coulomb's Law",
        "summary": "The electrostatic force between two point charges is proportional to the product of their charges and inversely proportional to the square of the distance.",
    },
    {
        "key": "em_wave_prediction",
        "layout_hint": "theorem",
        "tags": ["physics", "electromagnetism"],
        "title": "Electromagnetic Wave Prediction",
        "summary": "Maxwell's equations predict electromagnetic waves propagating at the speed of light.",
    },
    # -- Relativity --
    {
        "key": "special_relativity",
        "layout_hint": "law",
        "tags": ["physics", "relativity"],
        "title": "Special Relativity",
        "summary": "The laws of physics are the same in all inertial reference frames. The speed of light is constant for all observers.",
    },
    {
        "key": "mass_energy",
        "layout_hint": "theorem",
        "tags": ["physics", "relativity"],
        "title": "Mass-Energy Equivalence",
        "summary": "Energy and mass are interchangeable. E = mc^2.",
    },
    {
        "key": "time_dilation",
        "layout_hint": "theorem",
        "tags": ["physics", "relativity"],
        "title": "Time Dilation",
        "summary": "A clock moving relative to an observer ticks more slowly.",
    },
    {
        "key": "general_relativity",
        "layout_hint": "law",
        "tags": ["physics", "relativity"],
        "title": "General Relativity",
        "summary": "Gravity is a manifestation of spacetime curvature caused by mass and energy.",
    },
    # -- Quantum Mechanics --
    {
        "key": "schrodinger_eq",
        "layout_hint": "law",
        "tags": ["physics", "quantum-mechanics"],
        "title": "Schrodinger Equation",
        "summary": "The fundamental equation describing how the quantum state of a physical system changes over time.",
    },
    {
        "key": "heisenberg_uncertainty",
        "layout_hint": "theorem",
        "tags": ["physics", "quantum-mechanics"],
        "title": "Heisenberg Uncertainty Principle",
        "summary": "It is impossible to simultaneously know both the exact position and exact momentum of a particle.",
    },
    {
        "key": "wave_particle_duality",
        "layout_hint": "assertion",
        "tags": ["physics", "quantum-mechanics"],
        "title": "Wave-Particle Duality",
        "summary": "Quantum entities exhibit both wave-like and particle-like properties.",
    },
    {
        "key": "pauli_exclusion",
        "layout_hint": "law",
        "tags": ["physics", "quantum-mechanics"],
        "title": "Pauli Exclusion Principle",
        "summary": "No two identical fermions can simultaneously occupy the same quantum state.",
    },
    # -- Chemistry --
    {
        "key": "periodic_law",
        "layout_hint": "law",
        "tags": ["chemistry"],
        "title": "Periodic Law",
        "summary": "Properties of elements recur periodically when arranged by increasing atomic number.",
    },
    {
        "key": "law_conservation_mass",
        "layout_hint": "law",
        "tags": ["chemistry"],
        "title": "Law of Conservation of Mass",
        "summary": "In a closed chemical reaction, total mass of reactants equals total mass of products.",
    },
    {
        "key": "avogadro",
        "layout_hint": "law",
        "tags": ["chemistry"],
        "title": "Avogadro's Law",
        "summary": "Equal volumes of all gases, at the same temperature and pressure, contain the same number of molecules.",
    },
    {
        "key": "chemical_bonding",
        "layout_hint": "assertion",
        "tags": ["chemistry"],
        "title": "Chemical Bonding",
        "summary": "Atoms bond by sharing, transferring, or pooling electrons to achieve more stable configurations.",
    },
    # -- Biology / Evolution --
    {
        "key": "natural_selection",
        "layout_hint": "law",
        "tags": ["biology", "evolution"],
        "title": "Natural Selection",
        "summary": "Organisms with heritable traits better suited to their environment tend to survive and reproduce at higher rates.",
    },
    {
        "key": "common_descent",
        "layout_hint": "assertion",
        "tags": ["biology", "evolution"],
        "title": "Universal Common Descent",
        "summary": "All life on Earth shares a single common ancestor.",
    },
    {
        "key": "cell_theory",
        "layout_hint": "law",
        "tags": ["biology"],
        "title": "Cell Theory",
        "summary": "All living organisms are composed of one or more cells. The cell is the basic unit of life.",
    },
    # -- Genetics --
    {
        "key": "mendel_segregation",
        "layout_hint": "law",
        "tags": ["biology", "genetics"],
        "title": "Mendel's Law of Segregation",
        "summary": "During gamete formation, the two alleles for each gene separate so that each gamete carries only one allele.",
    },
    {
        "key": "mendel_independent",
        "layout_hint": "law",
        "tags": ["biology", "genetics"],
        "title": "Mendel's Law of Independent Assortment",
        "summary": "Genes for different traits assort independently during gamete formation.",
    },
    {
        "key": "dna_structure",
        "layout_hint": "evidence",
        "tags": ["biology", "genetics"],
        "title": "DNA Double Helix",
        "summary": "DNA consists of two polynucleotide chains wound in a double helix with complementary base pairing.",
    },
    {
        "key": "central_dogma",
        "layout_hint": "assertion",
        "tags": ["biology", "genetics"],
        "title": "Central Dogma of Molecular Biology",
        "summary": "Genetic information flows from DNA to RNA to protein.",
    },
    # -- Mathematics --
    {
        "key": "ftc",
        "layout_hint": "theorem",
        "tags": ["mathematics", "calculus"],
        "title": "Fundamental Theorem of Calculus",
        "summary": "Differentiation and integration are inverse operations.",
    },
    {
        "key": "pythagorean",
        "layout_hint": "theorem",
        "tags": ["mathematics"],
        "title": "Pythagorean Theorem",
        "summary": "In a right triangle, the square of the hypotenuse equals the sum of the squares of the other two sides.",
    },
    {
        "key": "euler_identity",
        "layout_hint": "theorem",
        "tags": ["mathematics"],
        "title": "Euler's Identity",
        "summary": "e^(i*pi) + 1 = 0 connects five fundamental constants.",
    },
    {
        "key": "noether",
        "layout_hint": "theorem",
        "tags": ["mathematics", "physics"],
        "title": "Noether's Theorem",
        "summary": "Every differentiable symmetry of the action has a corresponding conservation law.",
    },
]

# Relations between entries: (source_key, target_key, rel)
RELATIONS = [
    ("newton_2", "newton_1", "generalizes"),
    ("newton_3", "conservation_momentum", "derives"),
    ("newton_2", "universal_gravitation", "supports"),
    ("thermo_1", "conservation_energy", "specializes"),
    ("thermo_2", "thermo_1", "extends"),
    ("thermo_3", "thermo_2", "extends"),
    ("maxwell_equations", "coulombs_law", "generalizes"),
    ("maxwell_equations", "em_wave_prediction", "derives"),
    ("special_relativity", "newton_1", "generalizes"),
    ("special_relativity", "newton_2", "generalizes"),
    ("mass_energy", "special_relativity", "derives"),
    ("time_dilation", "special_relativity", "derives"),
    ("general_relativity", "special_relativity", "generalizes"),
    ("general_relativity", "universal_gravitation", "generalizes"),
    ("heisenberg_uncertainty", "schrodinger_eq", "derives"),
    ("wave_particle_duality", "schrodinger_eq", "supports"),
    ("pauli_exclusion", "schrodinger_eq", "derives"),
    ("pauli_exclusion", "chemical_bonding", "supports"),
    ("pauli_exclusion", "periodic_law", "supports"),
    ("natural_selection", "common_descent", "supports"),
    ("mendel_segregation", "natural_selection", "supports"),
    ("mendel_independent", "mendel_segregation", "extends"),
    ("dna_structure", "mendel_segregation", "supports"),
    ("dna_structure", "central_dogma", "supports"),
    ("noether", "conservation_energy", "derives"),
    ("noether", "conservation_momentum", "derives"),
    ("conservation_energy", "law_conservation_mass", "related_to"),
    ("mass_energy", "law_conservation_mass", "generalizes"),
    ("em_wave_prediction", "wave_particle_duality", "related_to"),
]


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------


def seed(base_url: str) -> None:
    base = api(base_url)
    client = httpx.Client()

    # -- 1. Register & login ------------------------------------------------
    print("=== Registering seed agent ===")
    try:
        auth = post(client, f"{base}/auth/register", {
            "handle": SEED_AGENT_HANDLE,
            "email": SEED_AGENT_EMAIL,
            "password": SEED_AGENT_PASSWORD,
        })
        token = auth["access_token"]
        agent_id = auth["agent"]["id"]
        print(f"  Registered: {agent_id}")
    except httpx.HTTPStatusError:
        print("  Registration failed (agent may already exist), trying login...")
        auth = post(client, f"{base}/auth/login", {
            "email": SEED_AGENT_EMAIL,
            "password": SEED_AGENT_PASSWORD,
        })
        token = auth["access_token"]
        agent_id = auth["agent"]["id"]
        print(f"  Logged in: {agent_id}")

    # -- 2. Create entries --------------------------------------------------
    print("\n=== Creating entries ===")
    entry_ids: dict[str, str] = {}
    entries_need_lookup: list[dict] = []

    # Fetch existing entries to skip duplicates
    existing_resp = get(client, f"{base}/entries", token=token, params={"limit": 200})
    existing_by_title = {e["title"]: e["id"] for e in existing_resp.get("items", [])}

    for entry_def in ENTRIES:
        if entry_def["title"] in existing_by_title:
            entry_ids[entry_def["key"]] = existing_by_title[entry_def["title"]]
            print(f"  {entry_def['key']}: {entry_ids[entry_def['key']]} (exists)")
            continue
        payload: dict = {
            "title": entry_def["title"],
            "layout_hint": entry_def.get("layout_hint"),
            "tags": entry_def.get("tags", []),
            "summary": entry_def.get("summary"),
        }
        resp = post(client, f"{base}/entries", payload, token=token, tolerate_500=True)
        if resp is not None:
            entry_ids[entry_def["key"]] = resp["id"]
            print(f"  {entry_def['key']}: {resp['id']}")
        else:
            entries_need_lookup.append(entry_def)
            print(f"  {entry_def['key']}: (committed, will look up)")

    # Resolve any IDs for entries that returned 500
    if entries_need_lookup:
        print(f"\n  Resolving {len(entries_need_lookup)} entry IDs...")
        all_resp = get(client, f"{base}/entries", token=token, params={"limit": 200})
        all_entries = all_resp.get("items", [])
        title_to_id = {e["title"]: e["id"] for e in all_entries}
        for entry_def in entries_need_lookup:
            eid = title_to_id.get(entry_def["title"])
            if eid:
                entry_ids[entry_def["key"]] = eid
                print(f"  {entry_def['key']}: {eid} (resolved)")
            else:
                print(f"  {entry_def['key']}: FAILED - not found in database!", file=sys.stderr)

    # -- 3. Create entry refs -----------------------------------------------
    print("\n=== Creating entry refs ===")
    for src_key, tgt_key, rel in RELATIONS:
        if src_key not in entry_ids or tgt_key not in entry_ids:
            print(f"  SKIP {src_key} -> {tgt_key}: missing entry IDs", file=sys.stderr)
            continue
        payload = {
            "from_entry_id": entry_ids[src_key],
            "to_entry_id": entry_ids[tgt_key],
            "rel": rel,
        }
        resp = post(client, f"{base}/entry-refs", payload, token=token)
        print(f"  {src_key} --[{rel}]-> {tgt_key}: {resp['id']}")

    # -- Summary ------------------------------------------------------------
    print("\n=== Seed complete ===")
    print(f"  Entries:    {len(entry_ids)}")
    print(f"  Entry Refs: {len(RELATIONS)}")
    print(f"\n  Agent: {SEED_AGENT_EMAIL} / {SEED_AGENT_PASSWORD}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Phiacta with foundational science entries")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Phiacta API base URL (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()
    seed(args.base_url)
