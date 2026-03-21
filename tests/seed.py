#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors
"""Seed the Phiacta database with test entries via the REST API.

Exercises every major API feature: entry CRUD, tags extension, file uploads,
edit proposals (create + merge + close), entry updates, archive/unarchive,
entry references with notes, and a second collaborator agent.

This is a test/development tool — not for production data.  Historical
knowledge should be added by agents using the API directly.

Usage:
    python tests/seed.py --base-url http://localhost:8000
    docker compose exec backend python tests/seed.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import base64
import os
import sys
import time

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.phiacta.com"
SEED_AGENT_HANDLE = "seed-agent"
SEED_AGENT_EMAIL = "seed@phiacta.com"
SEED_AGENT_PASSWORD = os.environ.get("PHIACTA_SEED_PASSWORD", "SeedAgent!2026")

COLLAB_AGENT_HANDLE = "collab-agent"
COLLAB_AGENT_EMAIL = "collab@phiacta.com"
COLLAB_AGENT_PASSWORD = os.environ.get("PHIACTA_COLLAB_PASSWORD", "CollabAgent!2026")

TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def api(base: str) -> str:
    return f"{base}/v1"


def _retry_after(response: httpx.Response) -> int:
    """Parse the Retry-After header from a 429 response.

    slowapi sends seconds as an integer string.  Falls back to 60s (one full
    rate-limit window) if the header is missing or unparseable.
    """
    raw = response.headers.get("Retry-After", "")
    try:
        return max(1, int(raw))
    except ValueError:
        return 60


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    json: dict | None = None,
    token: str | None = None,
    params: dict | None = None,
    tolerate_409: bool = False,
    tolerate_500: bool = False,
) -> dict | None:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for _ in range(10):
        r = client.request(method, url, json=json, headers=headers, params=params, timeout=TIMEOUT)
        if r.status_code == 429:
            wait = _retry_after(r)
            print(f"  rate-limited, retrying in {wait}s ...", file=sys.stderr)
            time.sleep(wait)
            continue
        if r.status_code >= 400:
            if tolerate_409 and r.status_code == 409:
                return None
            if tolerate_500 and r.status_code == 500:
                print("  WARN: got 500 (data likely committed anyway)", file=sys.stderr)
                return None
            print(f"  ERROR {r.status_code}: {r.text[:200]}", file=sys.stderr)
            r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return None  # unreachable


def post(client: httpx.Client, url: str, json: dict, **kw) -> dict | None:
    return _request(client, "POST", url, json=json, **kw)


def put(client: httpx.Client, url: str, json: dict, **kw) -> dict | None:
    return _request(client, "PUT", url, json=json, **kw)


def patch(client: httpx.Client, url: str, json: dict, **kw) -> dict | None:
    return _request(client, "PATCH", url, json=json, **kw)


def get(client: httpx.Client, url: str, **kw) -> dict | list | None:
    return _request(client, "GET", url, **kw)


def b64(text: str) -> str:
    """Base64-encode a UTF-8 string."""
    return base64.b64encode(text.encode()).decode()


def register_or_login(
    client: httpx.Client,
    base: str,
    handle: str,
    email: str,
    password: str,
) -> tuple[str, str]:
    """Register an agent or login if already exists.  Returns (token, agent_id)."""
    try:
        auth = post(client, f"{base}/auth/register", {
            "handle": handle, "email": email, "password": password,
        })
        return auth["access_token"], auth["agent"]["id"]
    except httpx.HTTPStatusError:
        auth = post(client, f"{base}/auth/login", {
            "email": email, "password": password,
        })
        return auth["access_token"], auth["agent"]["id"]


def wait_for_ready(
    client: httpx.Client,
    base: str,
    entry_id: str,
    token: str,
    *,
    max_wait: int = 60,
) -> bool:
    """Poll until an entry's repo_status becomes 'ready'.  Returns False on timeout."""
    for _ in range(max_wait // 2):
        detail = get(client, f"{base}/entries/{entry_id}", token=token)
        if detail.get("repo_status") == "ready":
            return True
        time.sleep(2)
    return False


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
        "tags": ["physics", "classical-mechanics", "newtonian-mechanics"],
        "title": "Newton's First Law",
        "summary": "An object at rest stays at rest, and an object in motion stays in uniform motion, unless acted upon by a net external force.",
        "content_format": "markdown",
        "content": (
            "# Newton's First Law of Motion\n\n"
            "Also known as the **law of inertia**, this principle states that an "
            "object will remain at rest or in uniform straight-line motion unless "
            "acted upon by an external net force.\n\n"
            "## Formal Statement\n\n"
            "In an inertial reference frame, a body remains at rest or moves at a "
            "constant velocity unless acted upon by a force.\n\n"
            "## Historical Context\n\n"
            "Published in *Principia Mathematica* (1687). Builds on Galileo's "
            "concept of inertia."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "newton_2",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics", "newtonian-mechanics"],
        "title": "Newton's Second Law",
        "summary": "The acceleration of an object is directly proportional to the net force acting on it and inversely proportional to its mass. F = ma.",
        "content_format": "latex",
        "content": (
            "\\section{Newton's Second Law of Motion}\n\n"
            "The net force on a body is equal to the product of its mass and "
            "acceleration:\n\n"
            "\\begin{equation}\n"
            "\\vec{F} = m\\vec{a}\n"
            "\\end{equation}\n\n"
            "More generally, force equals the time derivative of momentum:\n\n"
            "\\begin{equation}\n"
            "\\vec{F} = \\frac{d\\vec{p}}{dt}\n"
            "\\end{equation}\n\n"
            "where $\\vec{p} = m\\vec{v}$ is the momentum."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "newton_3",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics", "newtonian-mechanics"],
        "title": "Newton's Third Law",
        "summary": "For every action, there is an equal and opposite reaction.",
        "license": "CC-BY-4.0",
    },
    {
        "key": "conservation_energy",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics", "conservation-laws"],
        "title": "Law of Conservation of Energy",
        "summary": "Energy cannot be created or destroyed in an isolated system; it can only be transformed.",
        "content_format": "markdown",
        "content": (
            "# Conservation of Energy\n\n"
            "In an isolated system, the total energy remains constant over time. "
            "Energy may transform between kinetic, potential, thermal, and other "
            "forms, but the total is conserved.\n\n"
            "## Mathematical Form\n\n"
            "$$\\frac{dE_{\\text{total}}}{dt} = 0$$\n\n"
            "## Connection to Noether's Theorem\n\n"
            "Conservation of energy follows from the time-translation symmetry "
            "of the laws of physics."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "conservation_momentum",
        "layout_hint": "theorem",
        "tags": ["physics", "classical-mechanics", "conservation-laws"],
        "title": "Conservation of Linear Momentum",
        "summary": "In a closed system with no external forces, the total linear momentum is conserved.",
        "license": "CC-BY-4.0",
    },
    {
        "key": "universal_gravitation",
        "layout_hint": "law",
        "tags": ["physics", "classical-mechanics", "gravity"],
        "title": "Newton's Law of Universal Gravitation",
        "summary": "Every particle attracts every other particle with a force proportional to the product of their masses and inversely proportional to the square of the distance.",
        "content_format": "latex",
        "content": (
            "\\section{Universal Gravitation}\n\n"
            "\\begin{equation}\n"
            "F = G \\frac{m_1 m_2}{r^2}\n"
            "\\end{equation}\n\n"
            "where $G \\approx 6.674 \\times 10^{-11}$ N m$^2$ kg$^{-2}$ is the "
            "gravitational constant."
        ),
        "license": "CC-BY-4.0",
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
        "tags": ["physics", "thermodynamics", "conservation-laws"],
        "title": "First Law of Thermodynamics",
        "summary": "The change in internal energy of a closed system equals the heat added minus the work done.",
        "content_format": "latex",
        "content": (
            "\\section{First Law of Thermodynamics}\n\n"
            "\\begin{equation}\n"
            "\\Delta U = Q - W\n"
            "\\end{equation}\n\n"
            "In differential form: $dU = \\delta Q - \\delta W$."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "thermo_2",
        "layout_hint": "law",
        "tags": ["physics", "thermodynamics", "entropy"],
        "title": "Second Law of Thermodynamics",
        "summary": "The total entropy of an isolated system can only increase over time.",
        "content_format": "markdown",
        "content": (
            "# Second Law of Thermodynamics\n\n"
            "The entropy of an isolated system never decreases.\n\n"
            "## Clausius Statement\n\n"
            "Heat cannot spontaneously flow from a colder body to a hotter body.\n\n"
            "## Kelvin-Planck Statement\n\n"
            "No cyclic process can convert heat entirely into work."
        ),
        "license": "CC-BY-4.0",
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
        "content_format": "latex",
        "content": (
            "\\section{Maxwell's Equations}\n\n"
            "\\subsection{In Differential Form}\n\n"
            "\\begin{align}\n"
            "\\nabla \\cdot \\vec{E} &= \\frac{\\rho}{\\epsilon_0} \\\\\n"
            "\\nabla \\cdot \\vec{B} &= 0 \\\\\n"
            "\\nabla \\times \\vec{E} &= -\\frac{\\partial \\vec{B}}{\\partial t} \\\\\n"
            "\\nabla \\times \\vec{B} &= \\mu_0 \\vec{J} + \\mu_0 \\epsilon_0 "
            "\\frac{\\partial \\vec{E}}{\\partial t}\n"
            "\\end{align}"
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "coulombs_law",
        "layout_hint": "law",
        "tags": ["physics", "electromagnetism"],
        "title": "Coulomb's Law",
        "summary": "The electrostatic force between two point charges is proportional to the product of their charges and inversely proportional to the square of the distance.",
        "license": "CC-BY-4.0",
    },
    {
        "key": "em_wave_prediction",
        "layout_hint": "theorem",
        "tags": ["physics", "electromagnetism", "optics"],
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
        "content_format": "markdown",
        "content": (
            "# Special Relativity\n\n"
            "## Postulates\n\n"
            "1. The laws of physics are identical in all inertial frames.\n"
            "2. The speed of light in vacuum is the same for all observers.\n\n"
            "## Key Consequences\n\n"
            "- Time dilation\n"
            "- Length contraction\n"
            "- Relativity of simultaneity\n"
            "- Mass-energy equivalence"
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "mass_energy",
        "layout_hint": "theorem",
        "tags": ["physics", "relativity", "nuclear-physics"],
        "title": "Mass-Energy Equivalence",
        "summary": "Energy and mass are interchangeable. E = mc^2.",
        "content_format": "latex",
        "content": (
            "\\section{Mass-Energy Equivalence}\n\n"
            "\\begin{equation}\n"
            "E = mc^2\n"
            "\\end{equation}\n\n"
            "The full relativistic energy-momentum relation:\n\n"
            "\\begin{equation}\n"
            "E^2 = (pc)^2 + (mc^2)^2\n"
            "\\end{equation}"
        ),
        "license": "CC-BY-4.0",
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
        "tags": ["physics", "relativity", "gravity"],
        "title": "General Relativity",
        "summary": "Gravity is a manifestation of spacetime curvature caused by mass and energy.",
        "content_format": "latex",
        "content": (
            "\\section{Einstein Field Equations}\n\n"
            "\\begin{equation}\n"
            "G_{\\mu\\nu} + \\Lambda g_{\\mu\\nu} = "
            "\\frac{8\\pi G}{c^4} T_{\\mu\\nu}\n"
            "\\end{equation}\n\n"
            "where $G_{\\mu\\nu}$ is the Einstein tensor, $\\Lambda$ is the "
            "cosmological constant, and $T_{\\mu\\nu}$ is the stress-energy tensor."
        ),
        "license": "CC-BY-4.0",
    },
    # -- Quantum Mechanics --
    {
        "key": "schrodinger_eq",
        "layout_hint": "law",
        "tags": ["physics", "quantum-mechanics"],
        "title": "Schrodinger Equation",
        "summary": "The fundamental equation describing how the quantum state of a physical system changes over time.",
        "content_format": "latex",
        "content": (
            "\\section{Schr\\\"odinger Equation}\n\n"
            "\\subsection{Time-Dependent}\n\n"
            "\\begin{equation}\n"
            "i\\hbar \\frac{\\partial}{\\partial t} |\\Psi(t)\\rangle = "
            "\\hat{H} |\\Psi(t)\\rangle\n"
            "\\end{equation}\n\n"
            "\\subsection{Time-Independent}\n\n"
            "\\begin{equation}\n"
            "\\hat{H} |\\psi\\rangle = E |\\psi\\rangle\n"
            "\\end{equation}"
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "heisenberg_uncertainty",
        "layout_hint": "theorem",
        "tags": ["physics", "quantum-mechanics"],
        "title": "Heisenberg Uncertainty Principle",
        "summary": "It is impossible to simultaneously know both the exact position and exact momentum of a particle.",
        "content_format": "latex",
        "content": (
            "\\section{Heisenberg Uncertainty Principle}\n\n"
            "\\begin{equation}\n"
            "\\Delta x \\, \\Delta p \\geq \\frac{\\hbar}{2}\n"
            "\\end{equation}\n\n"
            "More generally, for any two non-commuting observables $A$ and $B$:\n\n"
            "\\begin{equation}\n"
            "\\sigma_A \\sigma_B \\geq \\frac{1}{2} |\\langle [\\hat{A}, \\hat{B}] \\rangle|\n"
            "\\end{equation}"
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "wave_particle_duality",
        "layout_hint": "assertion",
        "tags": ["physics", "quantum-mechanics", "optics"],
        "title": "Wave-Particle Duality",
        "summary": "Quantum entities exhibit both wave-like and particle-like properties.",
    },
    {
        "key": "pauli_exclusion",
        "layout_hint": "law",
        "tags": ["physics", "quantum-mechanics", "chemistry"],
        "title": "Pauli Exclusion Principle",
        "summary": "No two identical fermions can simultaneously occupy the same quantum state.",
        "license": "CC-BY-4.0",
    },
    # -- Chemistry --
    {
        "key": "periodic_law",
        "layout_hint": "law",
        "tags": ["chemistry", "periodic-table"],
        "title": "Periodic Law",
        "summary": "Properties of elements recur periodically when arranged by increasing atomic number.",
    },
    {
        "key": "law_conservation_mass",
        "layout_hint": "law",
        "tags": ["chemistry", "conservation-laws"],
        "title": "Law of Conservation of Mass",
        "summary": "In a closed chemical reaction, total mass of reactants equals total mass of products.",
        "license": "CC-BY-4.0",
    },
    {
        "key": "avogadro",
        "layout_hint": "law",
        "tags": ["chemistry", "gas-laws"],
        "title": "Avogadro's Law",
        "summary": "Equal volumes of all gases, at the same temperature and pressure, contain the same number of molecules.",
        "content_format": "plain",
        "content": (
            "Avogadro's Law\n\n"
            "At constant temperature and pressure, equal volumes of different "
            "gases contain the same number of molecules.\n\n"
            "V / n = k (constant T, P)\n\n"
            "Avogadro's number: N_A = 6.022 x 10^23 mol^-1"
        ),
    },
    {
        "key": "chemical_bonding",
        "layout_hint": "assertion",
        "tags": ["chemistry", "molecular-structure"],
        "title": "Chemical Bonding",
        "summary": "Atoms bond by sharing, transferring, or pooling electrons to achieve more stable configurations.",
    },
    # -- Biology / Evolution --
    {
        "key": "natural_selection",
        "layout_hint": "law",
        "tags": ["biology", "evolution", "ecology"],
        "title": "Natural Selection",
        "summary": "Organisms with heritable traits better suited to their environment tend to survive and reproduce at higher rates.",
        "content_format": "markdown",
        "content": (
            "# Natural Selection\n\n"
            "## Requirements\n\n"
            "1. **Variation** — individuals differ in traits\n"
            "2. **Heritability** — traits are passed to offspring\n"
            "3. **Differential fitness** — some variants survive and reproduce better\n\n"
            "## Mechanisms\n\n"
            "- Directional selection\n"
            "- Stabilizing selection\n"
            "- Disruptive selection\n"
            "- Sexual selection"
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "common_descent",
        "layout_hint": "assertion",
        "tags": ["biology", "evolution", "phylogenetics"],
        "title": "Universal Common Descent",
        "summary": "All life on Earth shares a single common ancestor.",
    },
    {
        "key": "cell_theory",
        "layout_hint": "law",
        "tags": ["biology", "cell-biology"],
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
        "license": "CC-BY-4.0",
    },
    {
        "key": "mendel_independent",
        "layout_hint": "law",
        "tags": ["biology", "genetics"],
        "title": "Mendel's Law of Independent Assortment",
        "summary": "Genes for different traits assort independently during gamete formation.",
        "license": "CC-BY-4.0",
    },
    {
        "key": "dna_structure",
        "layout_hint": "evidence",
        "tags": ["biology", "genetics", "molecular-biology"],
        "title": "DNA Double Helix",
        "summary": "DNA consists of two polynucleotide chains wound in a double helix with complementary base pairing.",
        "content_format": "markdown",
        "content": (
            "# DNA Double Helix Structure\n\n"
            "Watson and Crick (1953) determined that DNA consists of two "
            "antiparallel polynucleotide chains wound around a common axis.\n\n"
            "## Base Pairing Rules\n\n"
            "- Adenine (A) pairs with Thymine (T)\n"
            "- Guanine (G) pairs with Cytosine (C)\n\n"
            "## Key Features\n\n"
            "- Right-handed helix\n"
            "- 10 base pairs per turn\n"
            "- 3.4 nm pitch\n"
            "- Major and minor grooves"
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "central_dogma",
        "layout_hint": "assertion",
        "tags": ["biology", "genetics", "molecular-biology"],
        "title": "Central Dogma of Molecular Biology",
        "summary": "Genetic information flows from DNA to RNA to protein.",
    },
    # -- Mathematics --
    {
        "key": "ftc",
        "layout_hint": "theorem",
        "tags": ["mathematics", "calculus", "analysis"],
        "title": "Fundamental Theorem of Calculus",
        "summary": "Differentiation and integration are inverse operations.",
        "content_format": "latex",
        "content": (
            "\\section{Fundamental Theorem of Calculus}\n\n"
            "\\subsection{Part I}\n\n"
            "If $f$ is continuous on $[a,b]$ and "
            "$F(x) = \\int_a^x f(t)\\,dt$, then $F'(x) = f(x)$.\n\n"
            "\\subsection{Part II}\n\n"
            "\\begin{equation}\n"
            "\\int_a^b f(x)\\,dx = F(b) - F(a)\n"
            "\\end{equation}\n\n"
            "where $F$ is any antiderivative of $f$."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "pythagorean",
        "layout_hint": "theorem",
        "tags": ["mathematics", "geometry"],
        "title": "Pythagorean Theorem",
        "summary": "In a right triangle, the square of the hypotenuse equals the sum of the squares of the other two sides.",
        "content_format": "latex",
        "content": (
            "\\section{Pythagorean Theorem}\n\n"
            "For a right triangle with legs $a$, $b$ and hypotenuse $c$:\n\n"
            "\\begin{equation}\n"
            "a^2 + b^2 = c^2\n"
            "\\end{equation}\n\n"
            "Over 370 distinct proofs are known."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "euler_identity",
        "layout_hint": "theorem",
        "tags": ["mathematics", "complex-analysis"],
        "title": "Euler's Identity",
        "summary": "e^(i*pi) + 1 = 0 connects five fundamental constants.",
        "content_format": "latex",
        "content": (
            "\\section{Euler's Identity}\n\n"
            "\\begin{equation}\n"
            "e^{i\\pi} + 1 = 0\n"
            "\\end{equation}\n\n"
            "Connects the five most important constants in mathematics: "
            "$e$, $i$, $\\pi$, $1$, and $0$."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "noether",
        "layout_hint": "theorem",
        "tags": ["mathematics", "physics", "symmetry", "conservation-laws"],
        "title": "Noether's Theorem",
        "summary": "Every differentiable symmetry of the action has a corresponding conservation law.",
        "content_format": "markdown",
        "content": (
            "# Noether's Theorem\n\n"
            "Published by Emmy Noether in 1918.\n\n"
            "## Statement\n\n"
            "Every continuous symmetry of the action of a physical system "
            "corresponds to a conservation law.\n\n"
            "## Examples\n\n"
            "| Symmetry | Conservation Law |\n"
            "|---|---|\n"
            "| Time translation | Energy |\n"
            "| Spatial translation | Momentum |\n"
            "| Rotation | Angular momentum |"
        ),
        "license": "CC-BY-4.0",
    },
    # -- Computer Science (new domain) --
    {
        "key": "church_turing",
        "layout_hint": "assertion",
        "tags": ["computer-science", "computability", "mathematics"],
        "title": "Church-Turing Thesis",
        "summary": "Any function that is computable by an algorithm can be computed by a Turing machine.",
        "content_format": "markdown",
        "content": (
            "# Church-Turing Thesis\n\n"
            "The informal notion of 'effectively calculable' is captured exactly "
            "by the formal notion of computability by a Turing machine (or "
            "equivalently, by lambda calculus, recursive functions, etc.).\n\n"
            "## Note\n\n"
            "This is a thesis (assertion), not a theorem — it cannot be proven "
            "because 'effectively calculable' is not formally defined."
        ),
    },
    {
        "key": "halting_problem",
        "layout_hint": "theorem",
        "tags": ["computer-science", "computability", "mathematics"],
        "title": "Undecidability of the Halting Problem",
        "summary": "No general algorithm can determine whether an arbitrary program will halt or run forever.",
        "content_format": "markdown",
        "content": (
            "# Halting Problem\n\n"
            "Proven by Alan Turing (1936) via diagonalization.\n\n"
            "## Statement\n\n"
            "There is no Turing machine $H$ that, given a description of a "
            "Turing machine $M$ and input $w$, correctly decides whether $M$ "
            "halts on $w$."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "goedel_incompleteness",
        "layout_hint": "theorem",
        "tags": ["mathematics", "logic", "computer-science"],
        "title": "Godel's First Incompleteness Theorem",
        "summary": "Any consistent formal system capable of expressing arithmetic contains true statements that cannot be proved within the system.",
        "content_format": "markdown",
        "content": (
            "# Godel's First Incompleteness Theorem (1931)\n\n"
            "For any consistent, recursively enumerable formal system $F$ "
            "capable of expressing basic arithmetic, there exists a sentence "
            "$G_F$ such that:\n\n"
            "1. $G_F$ is true (in the standard model of arithmetic)\n"
            "2. $G_F$ is not provable in $F$\n"
            "3. $\\neg G_F$ is not provable in $F$"
        ),
        "license": "CC-BY-4.0",
    },
    # -- Statistics (new domain) --
    {
        "key": "bayes_theorem",
        "layout_hint": "theorem",
        "tags": ["mathematics", "statistics", "probability"],
        "title": "Bayes' Theorem",
        "summary": "Describes the probability of an event based on prior knowledge of conditions related to the event.",
        "content_format": "latex",
        "content": (
            "\\section{Bayes' Theorem}\n\n"
            "\\begin{equation}\n"
            "P(A|B) = \\frac{P(B|A) \\, P(A)}{P(B)}\n"
            "\\end{equation}\n\n"
            "where $P(A|B)$ is the posterior probability, $P(B|A)$ is the "
            "likelihood, $P(A)$ is the prior, and $P(B)$ is the evidence."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "central_limit",
        "layout_hint": "theorem",
        "tags": ["mathematics", "statistics", "probability"],
        "title": "Central Limit Theorem",
        "summary": "The distribution of sample means approaches a normal distribution as sample size increases, regardless of the population distribution.",
        "content_format": "latex",
        "content": (
            "\\section{Central Limit Theorem}\n\n"
            "Let $X_1, X_2, \\ldots, X_n$ be i.i.d. random variables with "
            "mean $\\mu$ and variance $\\sigma^2$. Then:\n\n"
            "\\begin{equation}\n"
            "\\frac{\\bar{X}_n - \\mu}{\\sigma / \\sqrt{n}} "
            "\\xrightarrow{d} N(0, 1)\n"
            "\\end{equation}\n\n"
            "as $n \\to \\infty$."
        ),
        "license": "CC-BY-4.0",
    },
    {
        "key": "law_large_numbers",
        "layout_hint": "theorem",
        "tags": ["mathematics", "statistics", "probability"],
        "title": "Law of Large Numbers",
        "summary": "As a sample size grows, its mean converges to the expected value.",
        "content_format": "plain",
        "content": (
            "Law of Large Numbers\n\n"
            "Strong form: The sample average converges almost surely to the "
            "expected value as n -> infinity.\n\n"
            "Weak form: The sample average converges in probability to the "
            "expected value."
        ),
    },
]

# Relations between entries: (source_key, target_key, rel, note)
RELATIONS = [
    ("newton_2", "newton_1", "generalizes", "Second law reduces to first law when F=0"),
    ("newton_3", "conservation_momentum", "derives", None),
    ("newton_2", "universal_gravitation", "supports", "F=ma applied to gravitational force"),
    ("thermo_1", "conservation_energy", "specializes", "First law is energy conservation for thermodynamic systems"),
    ("thermo_2", "thermo_1", "extends", None),
    ("thermo_3", "thermo_2", "extends", None),
    ("maxwell_equations", "coulombs_law", "generalizes", "Gauss's law (first Maxwell equation) generalizes Coulomb's law"),
    ("maxwell_equations", "em_wave_prediction", "derives", "Wave equation emerges from combining Maxwell's equations"),
    ("special_relativity", "newton_1", "generalizes", "Newtonian mechanics is the low-velocity limit"),
    ("special_relativity", "newton_2", "generalizes", "Newtonian mechanics is the low-velocity limit"),
    ("mass_energy", "special_relativity", "derives", "Direct consequence of Lorentz invariance"),
    ("time_dilation", "special_relativity", "derives", None),
    ("general_relativity", "special_relativity", "generalizes", "SR is the flat-spacetime limit of GR"),
    ("general_relativity", "universal_gravitation", "generalizes", "Newtonian gravity is the weak-field limit"),
    ("heisenberg_uncertainty", "schrodinger_eq", "derives", "Follows from wave-function formalism"),
    ("wave_particle_duality", "schrodinger_eq", "supports", None),
    ("pauli_exclusion", "schrodinger_eq", "derives", "Consequence of antisymmetric wave functions"),
    ("pauli_exclusion", "chemical_bonding", "supports", "Determines electron shell structure"),
    ("pauli_exclusion", "periodic_law", "supports", "Electron configuration explains periodicity"),
    ("natural_selection", "common_descent", "supports", None),
    ("mendel_segregation", "natural_selection", "supports", "Provides mechanism for heritable variation"),
    ("mendel_independent", "mendel_segregation", "extends", None),
    ("dna_structure", "mendel_segregation", "supports", "Physical basis for allele segregation during meiosis"),
    ("dna_structure", "central_dogma", "supports", "Explains information storage mechanism"),
    ("noether", "conservation_energy", "derives", "Time-translation symmetry yields energy conservation"),
    ("noether", "conservation_momentum", "derives", "Spatial-translation symmetry yields momentum conservation"),
    ("conservation_energy", "law_conservation_mass", "related_to", None),
    ("mass_energy", "law_conservation_mass", "generalizes", "Mass is a form of energy; combined conservation"),
    ("em_wave_prediction", "wave_particle_duality", "related_to", None),
    # New cross-domain connections
    ("halting_problem", "church_turing", "derives", "Uses Turing machine model from Church-Turing thesis"),
    ("goedel_incompleteness", "halting_problem", "related_to", "Both proven by diagonalization; deeply connected"),
    ("central_limit", "law_large_numbers", "extends", "CLT gives the rate of convergence; LLN gives the convergence itself"),
    ("bayes_theorem", "central_limit", "related_to", "Bayesian updating and frequentist convergence are complementary"),
    ("noether", "general_relativity", "supports", "Diffeomorphism invariance yields conservation of energy-momentum tensor"),
]

# Files to upload to specific entries (key -> list of (path, content))
FILES = {
    "pythagorean": [
        ("proof.md", (
            "# Proof of the Pythagorean Theorem (Euclid, Book I, Prop. 47)\n\n"
            "Consider a right triangle with legs $a$, $b$ and hypotenuse $c$.\n\n"
            "Construct squares on each side. The area of the square on the "
            "hypotenuse equals the sum of the areas on the legs.\n\n"
            "## Algebraic Proof\n\n"
            "Arrange four copies of the triangle inside a square of side $(a+b)$:\n\n"
            "$(a+b)^2 = c^2 + 4 \\cdot \\frac{ab}{2}$\n\n"
            "$a^2 + 2ab + b^2 = c^2 + 2ab$\n\n"
            "$a^2 + b^2 = c^2$ QED"
        )),
    ],
    "euler_identity": [
        ("derivation.tex", (
            "\\documentclass{article}\n"
            "\\begin{document}\n"
            "\\section{Derivation of Euler's Identity}\n\n"
            "Start from Euler's formula:\n"
            "\\[ e^{ix} = \\cos x + i \\sin x \\]\n\n"
            "Set $x = \\pi$:\n"
            "\\[ e^{i\\pi} = \\cos \\pi + i \\sin \\pi = -1 + 0 = -1 \\]\n\n"
            "Therefore:\n"
            "\\[ e^{i\\pi} + 1 = 0 \\]\n"
            "\\end{document}"
        )),
    ],
    "schrodinger_eq": [
        ("examples/particle-in-box.md", (
            "# Particle in a 1D Box\n\n"
            "## Setup\n\n"
            "Potential: V(x) = 0 for 0 < x < L, infinity otherwise.\n\n"
            "## Solution\n\n"
            "Energy levels: $E_n = \\frac{n^2 \\pi^2 \\hbar^2}{2mL^2}$\n\n"
            "Wave functions: $\\psi_n(x) = \\sqrt{\\frac{2}{L}} \\sin\\left(\\frac{n\\pi x}{L}\\right)$"
        )),
    ],
    "bayes_theorem": [
        ("examples/medical-test.md", (
            "# Bayesian Reasoning: Medical Test Example\n\n"
            "A disease affects 1% of the population. A test has:\n"
            "- Sensitivity (true positive rate): 99%\n"
            "- Specificity (true negative rate): 95%\n\n"
            "## Question\n\n"
            "If a person tests positive, what is the probability they have "
            "the disease?\n\n"
            "## Solution\n\n"
            "P(D|+) = P(+|D) * P(D) / P(+)\n"
            "       = 0.99 * 0.01 / (0.99 * 0.01 + 0.05 * 0.99)\n"
            "       = 0.0099 / 0.0594\n"
            "       = 16.7%\n\n"
            "Despite the high sensitivity, most positive results are false "
            "positives due to the low base rate."
        )),
    ],
    "natural_selection": [
        ("data/peppered-moth.csv", (
            "year,light_form_pct,dark_form_pct,soot_index\n"
            "1848,95,5,10\n"
            "1860,80,20,35\n"
            "1880,50,50,65\n"
            "1900,15,85,90\n"
            "1920,10,90,95\n"
            "1960,20,80,70\n"
            "1980,60,40,30\n"
            "2000,85,15,10\n"
        )),
    ],
}

# Edit proposals: (entry_key, proposer="collab", title, body, files)
EDIT_PROPOSALS = [
    (
        "newton_1",
        "Add historical references",
        "Adding references to Galileo's earlier work on inertia and the "
        "original Latin text from Principia.",
        [
            ("references.md", (
                "# References\n\n"
                "1. Newton, I. (1687). *Philosophiae Naturalis Principia "
                "Mathematica*.\n"
                "2. Galilei, G. (1632). *Dialogue Concerning the Two Chief "
                "World Systems*.\n"
                "3. Mach, E. (1883). *The Science of Mechanics*."
            )),
        ],
    ),
    (
        "thermo_2",
        "Add statistical mechanics perspective",
        "Extending the entry with Boltzmann's statistical interpretation of entropy.",
        [
            ("statistical-interpretation.md", (
                "# Statistical Mechanics Interpretation\n\n"
                "Boltzmann's entropy formula:\n\n"
                "$S = k_B \\ln \\Omega$\n\n"
                "where $\\Omega$ is the number of microstates corresponding "
                "to a given macrostate."
            )),
        ],
    ),
]

# Entries to update via PATCH (entry_key, update_payload)
UPDATES = [
    ("newton_1", {"summary": (
        "An object at rest stays at rest, and an object in motion stays in "
        "uniform motion, unless acted upon by a net external force. Also "
        "known as the law of inertia. First published in Principia (1687)."
    )}),
    ("thermo_0", {"license": "CC0-1.0"}),
    ("cell_theory", {"license": "CC-BY-4.0", "content_format": "markdown"}),
]

# Entry to archive then unarchive (exercises both endpoints)
ARCHIVE_KEY = "thermo_0"


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------


def seed(base_url: str) -> None:
    base = api(base_url)
    client = httpx.Client()
    counters: dict[str, int] = {
        "entries": 0,
        "tags": 0,
        "refs": 0,
        "files": 0,
        "edits": 0,
        "updates": 0,
    }

    # -- 1. Register & login both agents -----------------------------------
    print("=== Registering agents ===")
    token, agent_id = register_or_login(
        client, base, SEED_AGENT_HANDLE, SEED_AGENT_EMAIL, SEED_AGENT_PASSWORD,
    )
    print(f"  seed-agent: {agent_id}")

    collab_token, collab_id = register_or_login(
        client, base, COLLAB_AGENT_HANDLE, COLLAB_AGENT_EMAIL, COLLAB_AGENT_PASSWORD,
    )
    print(f"  collab-agent: {collab_id}")

    # -- 2. Create entries -------------------------------------------------
    print("\n=== Creating entries ===")
    entry_ids: dict[str, str] = {}
    entries_need_lookup: list[dict] = []

    # Fetch existing entries (including archived) to skip duplicates
    existing_resp = get(client, f"{base}/entries", token=token, params={"limit": 200, "status": "all"})
    existing_by_title = {e["title"]: e["id"] for e in existing_resp.get("items", [])}

    for entry_def in ENTRIES:
        if entry_def["title"] in existing_by_title:
            entry_ids[entry_def["key"]] = existing_by_title[entry_def["title"]]
            print(f"  {entry_def['key']}: {entry_ids[entry_def['key']]} (exists)")
            continue
        payload: dict = {
            "title": entry_def["title"],
            "layout_hint": entry_def.get("layout_hint"),
            "summary": entry_def.get("summary"),
        }
        if entry_def.get("content_format"):
            payload["content_format"] = entry_def["content_format"]
        if entry_def.get("content"):
            payload["content"] = entry_def["content"]
        if entry_def.get("license"):
            payload["license"] = entry_def["license"]
        resp = post(client, f"{base}/entries", payload, token=token, tolerate_500=True)
        if resp is not None:
            entry_ids[entry_def["key"]] = resp["id"]
            counters["entries"] += 1
            print(f"  {entry_def['key']}: {resp['id']}")
        else:
            entries_need_lookup.append(entry_def)
            print(f"  {entry_def['key']}: (committed, will look up)")

    # Resolve any IDs for entries that returned 500
    if entries_need_lookup:
        print(f"\n  Resolving {len(entries_need_lookup)} entry IDs...")
        all_resp = get(client, f"{base}/entries", token=token, params={"limit": 200, "status": "all"})
        all_entries = all_resp.get("items", [])
        title_to_id = {e["title"]: e["id"] for e in all_entries}
        for entry_def in entries_need_lookup:
            eid = title_to_id.get(entry_def["title"])
            if eid:
                entry_ids[entry_def["key"]] = eid
                counters["entries"] += 1
                print(f"  {entry_def['key']}: {eid} (resolved)")
            else:
                print(f"  {entry_def['key']}: FAILED - not found in database!", file=sys.stderr)

    # -- 3. Set tags via extension API -------------------------------------
    print("\n=== Setting tags ===")
    for entry_def in ENTRIES:
        key = entry_def["key"]
        tags = entry_def.get("tags", [])
        if not tags or key not in entry_ids:
            continue
        resp = put(
            client,
            f"{base}/extensions/tags/{entry_ids[key]}",
            {"tags": tags},
            token=token,
            tolerate_409=True,
        )
        if resp is not None:
            counters["tags"] += 1
            print(f"  {key}: {tags}")
        else:
            print(f"  {key}: skipped (conflict)")

    # -- 4. Create entry refs with notes -----------------------------------
    print("\n=== Creating entry refs ===")
    for src_key, tgt_key, rel, note in RELATIONS:
        if src_key not in entry_ids or tgt_key not in entry_ids:
            print(f"  SKIP {src_key} -> {tgt_key}: missing entry IDs", file=sys.stderr)
            continue
        payload = {
            "from_entry_id": entry_ids[src_key],
            "to_entry_id": entry_ids[tgt_key],
            "rel": rel,
        }
        if note:
            payload["note"] = note
        resp = post(client, f"{base}/entry-refs", payload, token=token)
        counters["refs"] += 1
        note_flag = " (+note)" if note else ""
        print(f"  {src_key} --[{rel}]-> {tgt_key}: {resp['id']}{note_flag}")

    # -- 5. Wait for repos, then upload files ------------------------------
    print("\n=== Uploading files ===")
    for entry_key, file_list in FILES.items():
        if entry_key not in entry_ids:
            print(f"  SKIP {entry_key}: entry not found", file=sys.stderr)
            continue
        eid = entry_ids[entry_key]
        if not wait_for_ready(client, base, eid, token, max_wait=60):
            print(f"  SKIP {entry_key}: repo not ready after 60s", file=sys.stderr)
            continue
        for path, content in file_list:
            resp = put(
                client,
                f"{base}/entries/{eid}/files/{path}",
                {"content": b64(content), "message": f"Seed: add {path}"},
                token=token,
            )
            if resp:
                counters["files"] += 1
                print(f"  {entry_key}/{path}: {resp.get('sha', 'ok')[:12]}")

    # -- 6. Update entry metadata via PATCH --------------------------------
    print("\n=== Updating entries ===")
    for entry_key, update_payload in UPDATES:
        if entry_key not in entry_ids:
            print(f"  SKIP {entry_key}: entry not found", file=sys.stderr)
            continue
        eid = entry_ids[entry_key]
        if not wait_for_ready(client, base, eid, token, max_wait=30):
            print(f"  SKIP {entry_key}: repo not ready", file=sys.stderr)
            continue
        resp = patch(client, f"{base}/entries/{eid}", update_payload, token=token)
        if resp:
            counters["updates"] += 1
            fields = ", ".join(update_payload.keys())
            print(f"  {entry_key}: updated {fields}")

    # -- 7. Archive and unarchive ------------------------------------------
    print("\n=== Archive / unarchive ===")
    if ARCHIVE_KEY in entry_ids:
        eid = entry_ids[ARCHIVE_KEY]
        if wait_for_ready(client, base, eid, token, max_wait=30):
            resp = post(client, f"{base}/entries/{eid}/archive", {}, token=token, tolerate_409=True)
            if resp and resp.get("status") == "archived":
                print(f"  {ARCHIVE_KEY}: archived")
                resp = post(client, f"{base}/entries/{eid}/unarchive", {}, token=token)
                if resp and resp.get("status") == "active":
                    print(f"  {ARCHIVE_KEY}: unarchived")
            else:
                print(f"  {ARCHIVE_KEY}: skipped (already archived or not ready)")
        else:
            print(f"  {ARCHIVE_KEY}: skipped (repo not ready)")

    # -- 8. Create edit proposals (as collab-agent) ------------------------
    print("\n=== Creating edit proposals ===")
    for entry_key, title, body, files in EDIT_PROPOSALS:
        if entry_key not in entry_ids:
            print(f"  SKIP {entry_key}: entry not found", file=sys.stderr)
            continue
        eid = entry_ids[entry_key]
        if not wait_for_ready(client, base, eid, token, max_wait=30):
            print(f"  SKIP {entry_key}: repo not ready", file=sys.stderr)
            continue
        payload = {
            "title": title,
            "body": body,
            "files": [{"path": p, "content": b64(c)} for p, c in files],
        }
        resp = post(client, f"{base}/entries/{eid}/edits", payload, token=collab_token)
        if resp:
            counters["edits"] += 1
            print(f"  {entry_key} PR#{resp.get('number')}: {title}")

    # -- 9. Merge first proposal, close second -----------------------------
    print("\n=== Merge / close proposals ===")
    if len(EDIT_PROPOSALS) >= 1:
        entry_key = EDIT_PROPOSALS[0][0]
        if entry_key in entry_ids:
            eid = entry_ids[entry_key]
            edits = get(client, f"{base}/entries/{eid}/edits", token=token, params={"state": "open"})
            if isinstance(edits, list) and edits:
                pr_num = edits[0]["number"]
                resp = post(client, f"{base}/entries/{eid}/edits/{pr_num}/merge", {}, token=token)
                if resp:
                    print(f"  {entry_key} PR#{pr_num}: merged ({resp.get('sha', '')[:12]})")

    if len(EDIT_PROPOSALS) >= 2:
        entry_key = EDIT_PROPOSALS[1][0]
        if entry_key in entry_ids:
            eid = entry_ids[entry_key]
            edits = get(client, f"{base}/entries/{eid}/edits", token=token, params={"state": "open"})
            if isinstance(edits, list) and edits:
                pr_num = edits[0]["number"]
                resp = post(client, f"{base}/entries/{eid}/edits/{pr_num}/close", {}, token=token)
                if resp:
                    print(f"  {entry_key} PR#{pr_num}: closed")

    # -- Summary -----------------------------------------------------------
    print("\n=== Seed complete ===")
    print(f"  Entries:        {len(entry_ids)}")
    print(f"  Tags set:       {counters['tags']}")
    print(f"  Entry refs:     {counters['refs']}")
    print(f"  Files uploaded: {counters['files']}")
    print(f"  Edit proposals: {counters['edits']}")
    print(f"  Entry updates:  {counters['updates']}")
    print(f"\n  seed-agent:  {SEED_AGENT_EMAIL} / {SEED_AGENT_PASSWORD}")
    print(f"  collab-agent: {COLLAB_AGENT_EMAIL} / {COLLAB_AGENT_PASSWORD}")


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
