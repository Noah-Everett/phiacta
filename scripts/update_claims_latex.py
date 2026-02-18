#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors
"""Update all seed claims to v2 with Markdown + LaTeX formatting.

Usage:
    python scripts/update_claims_latex.py
    python scripts/update_claims_latex.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx

DEFAULT_BASE_URL = "https://api.phiacta.com"
SEED_AGENT_EMAIL = "seed@phiacta.com"
SEED_AGENT_PASSWORD = os.environ.get("PHIACTA_SEED_PASSWORD", "SeedAgent!2026")
TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# v2 content: Markdown + LaTeX versions of every seed claim
# keyed by v1 content prefix (first 40 chars) for matching
# ---------------------------------------------------------------------------

V2_CLAIMS: dict[str, dict] = {
    "Newton's First Law": {
        "content": (
            "**Newton's First Law** (Law of Inertia): An object at rest stays at rest, "
            "and an object in motion stays in uniform motion, unless acted upon by a "
            "net external force.\n\n"
            "$$\\vec{F}_{\\text{net}} = 0 \\implies \\frac{d\\vec{v}}{dt} = 0$$"
        ),
        "formal_content": r"\vec{F}_{\text{net}} = 0 \implies \frac{d\vec{v}}{dt} = 0",
    },
    "Newton's Second Law": {
        "content": (
            "**Newton's Second Law**: The acceleration of an object is directly "
            "proportional to the net force acting on it and inversely proportional "
            "to its mass.\n\n"
            "$$\\vec{F} = m\\vec{a} = \\frac{d\\vec{p}}{dt}$$"
        ),
        "formal_content": r"\vec{F} = m\vec{a} = \frac{d\vec{p}}{dt}",
    },
    "Newton's Third Law": {
        "content": (
            "**Newton's Third Law**: For every action, there is an equal and opposite "
            "reaction. When object A exerts a force on object B, object B simultaneously "
            "exerts an equal and opposite force on object A.\n\n"
            "$$\\vec{F}_{AB} = -\\vec{F}_{BA}$$"
        ),
        "formal_content": r"\vec{F}_{AB} = -\vec{F}_{BA}",
    },
    "Law of Conservation of Energy": {
        "content": (
            "**Law of Conservation of Energy**: Energy cannot be created or destroyed "
            "in an isolated system; it can only be transformed from one form to another. "
            "The total energy of an isolated system remains constant.\n\n"
            "$$\\frac{dE}{dt} = 0 \\quad \\text{(isolated system)}$$"
        ),
        "formal_content": r"\frac{dE}{dt} = 0 \text{ for isolated systems}",
    },
    "Conservation of Linear Momentum": {
        "content": (
            "**Conservation of Linear Momentum**: In a closed system with no external "
            "forces, the total linear momentum is conserved. This follows from Newton's Third Law.\n\n"
            "$$\\vec{F}_{\\text{ext}} = 0 \\implies \\frac{d\\vec{p}_{\\text{total}}}{dt} = 0$$"
        ),
        "formal_content": r"\vec{F}_{\text{ext}} = 0 \implies \frac{d\vec{p}_{\text{total}}}{dt} = 0",
    },
    "Newton's Law of Universal Gravitation": {
        "content": (
            "**Newton's Law of Universal Gravitation**: Every particle of matter attracts "
            "every other particle with a force proportional to the product of their masses "
            "and inversely proportional to the square of the distance between them.\n\n"
            "$$F = G\\frac{m_1 m_2}{r^2}$$\n\n"
            "where $G \\approx 6.674 \\times 10^{-11}\\;\\text{N m}^2\\text{kg}^{-2}$."
        ),
        "formal_content": r"F = G\frac{m_1 m_2}{r^2}",
    },
    "Zeroth Law of Thermodynamics": {
        "content": (
            "**Zeroth Law of Thermodynamics**: If two thermodynamic systems are each in "
            "thermal equilibrium with a third system, they are in thermal equilibrium "
            "with each other. This establishes temperature as a fundamental measurable property.\n\n"
            "If $A \\sim C$ and $B \\sim C$, then $A \\sim B$ (where $\\sim$ denotes thermal equilibrium)."
        ),
    },
    "First Law of Thermodynamics": {
        "content": (
            "**First Law of Thermodynamics**: The change in internal energy of a closed "
            "system equals the heat added to the system minus the work done by the system.\n\n"
            "$$dU = \\delta Q - \\delta W$$"
        ),
        "formal_content": r"dU = \delta Q - \delta W",
    },
    "Second Law of Thermodynamics": {
        "content": (
            "**Second Law of Thermodynamics**: In any cyclic process, the total entropy "
            "of an isolated system can only increase over time. Heat cannot spontaneously "
            "flow from a colder body to a hotter body.\n\n"
            "$$dS \\geq \\frac{\\delta Q}{T}$$\n\n"
            "with equality holding for reversible processes."
        ),
        "formal_content": r"dS \geq \frac{\delta Q}{T}",
    },
    "Third Law of Thermodynamics": {
        "content": (
            "**Third Law of Thermodynamics**: As the temperature of a system approaches "
            "absolute zero, the entropy of the system approaches a minimum value "
            "(zero for a perfect crystal).\n\n"
            "$$\\lim_{T \\to 0} S = 0 \\quad \\text{(perfect crystal)}$$"
        ),
        "formal_content": r"\lim_{T \to 0} S = 0 \text{ for perfect crystals}",
    },
    "Maxwell's Equations: Four partial": {
        "content": (
            "**Maxwell's Equations**: Four partial differential equations that together "
            "form the foundation of classical electromagnetism:\n\n"
            "$$\\nabla \\cdot \\vec{E} = \\frac{\\rho}{\\varepsilon_0}$$\n\n"
            "$$\\nabla \\cdot \\vec{B} = 0$$\n\n"
            "$$\\nabla \\times \\vec{E} = -\\frac{\\partial \\vec{B}}{\\partial t}$$\n\n"
            "$$\\nabla \\times \\vec{B} = \\mu_0 \\vec{J} + \\mu_0 \\varepsilon_0 "
            "\\frac{\\partial \\vec{E}}{\\partial t}$$"
        ),
        "formal_content": (
            r"\nabla \cdot \vec{E} = \frac{\rho}{\varepsilon_0}; \; "
            r"\nabla \cdot \vec{B} = 0; \; "
            r"\nabla \times \vec{E} = -\frac{\partial \vec{B}}{\partial t}; \; "
            r"\nabla \times \vec{B} = \mu_0 \vec{J} + \mu_0 \varepsilon_0 \frac{\partial \vec{E}}{\partial t}"
        ),
    },
    "Coulomb's Law": {
        "content": (
            "**Coulomb's Law**: The electrostatic force between two point charges is "
            "directly proportional to the product of their charges and inversely "
            "proportional to the square of the distance between them.\n\n"
            "$$F = k_e \\frac{q_1 q_2}{r^2}$$\n\n"
            "where $k_e = \\frac{1}{4\\pi\\varepsilon_0} \\approx 8.988 \\times 10^9\\;\\text{N m}^2\\text{C}^{-2}$."
        ),
        "formal_content": r"F = k_e \frac{q_1 q_2}{r^2}",
    },
    "Maxwell's equations predict": {
        "content": (
            "**Electromagnetic Wave Prediction**: Maxwell's equations predict the existence "
            "of electromagnetic waves propagating at the speed of light, unifying optics "
            "with electromagnetism.\n\n"
            "$$c = \\frac{1}{\\sqrt{\\mu_0 \\varepsilon_0}} \\approx 3 \\times 10^8\\;\\text{m/s}$$"
        ),
        "formal_content": r"c = \frac{1}{\sqrt{\mu_0 \varepsilon_0}}",
    },
    "Special Relativity: The laws": {
        "content": (
            "**Special Relativity**: The laws of physics are the same in all inertial "
            "reference frames. The speed of light in vacuum is constant for all observers, "
            "denoted $c$, regardless of their relative motion.\n\n"
            "The Lorentz factor: $\\gamma = \\frac{1}{\\sqrt{1 - v^2/c^2}}$"
        ),
    },
    "Mass-Energy Equivalence": {
        "content": (
            "**Mass-Energy Equivalence**: Energy and mass are interchangeable. "
            "A body at rest has an intrinsic energy proportional to its mass.\n\n"
            "$$E = mc^2$$\n\n"
            "More generally, $E^2 = (pc)^2 + (mc^2)^2$ for a particle with momentum $p$."
        ),
        "formal_content": r"E = mc^2; \quad E^2 = (pc)^2 + (mc^2)^2",
    },
    "Time Dilation": {
        "content": (
            "**Time Dilation**: A clock moving relative to an observer ticks more slowly "
            "than a clock at rest with respect to that observer. Time intervals are "
            "frame-dependent.\n\n"
            "$$\\Delta t' = \\gamma \\Delta t = \\frac{\\Delta t}{\\sqrt{1 - v^2/c^2}}$$"
        ),
        "formal_content": r"\Delta t' = \frac{\Delta t}{\sqrt{1 - v^2/c^2}}",
    },
    "General Relativity: Gravity is not": {
        "content": (
            "**General Relativity**: Gravity is not a force but a manifestation of "
            "spacetime curvature caused by mass and energy. The **Einstein field equations** "
            "relate the geometry of spacetime to the distribution of matter:\n\n"
            "$$G_{\\mu\\nu} + \\Lambda g_{\\mu\\nu} = \\frac{8\\pi G}{c^4} T_{\\mu\\nu}$$"
        ),
        "formal_content": r"G_{\mu\nu} + \Lambda g_{\mu\nu} = \frac{8\pi G}{c^4} T_{\mu\nu}",
    },
    "Schrodinger Equation": {
        "content": (
            "**Schr\u00f6dinger Equation**: The fundamental equation of quantum mechanics "
            "that describes how the quantum state of a physical system changes over time.\n\n"
            "$$i\\hbar \\frac{\\partial}{\\partial t}|\\psi\\rangle = \\hat{H}|\\psi\\rangle$$\n\n"
            "For a single particle: $i\\hbar \\frac{\\partial \\psi}{\\partial t} = "
            "-\\frac{\\hbar^2}{2m}\\nabla^2 \\psi + V\\psi$"
        ),
        "formal_content": r"i\hbar \frac{\partial}{\partial t}|\psi\rangle = \hat{H}|\psi\rangle",
    },
    "Heisenberg Uncertainty Principle": {
        "content": (
            "**Heisenberg Uncertainty Principle**: It is impossible to simultaneously know "
            "both the exact position and exact momentum of a particle. The product of "
            "the uncertainties has a fundamental lower bound.\n\n"
            "$$\\Delta x \\cdot \\Delta p \\geq \\frac{\\hbar}{2}$$\n\n"
            "More generally, for any two observables $\\hat{A}$ and $\\hat{B}$: "
            "$\\sigma_A \\sigma_B \\geq \\frac{1}{2}|\\langle[\\hat{A}, \\hat{B}]\\rangle|$"
        ),
        "formal_content": r"\Delta x \cdot \Delta p \geq \frac{\hbar}{2}",
    },
    "Wave-Particle Duality": {
        "content": (
            "**Wave-Particle Duality**: Quantum entities exhibit both wave-like and "
            "particle-like properties. The **de Broglie relation** connects a particle's "
            "momentum to its wavelength:\n\n"
            "$$\\lambda = \\frac{h}{p}$$\n\n"
            "where $h \\approx 6.626 \\times 10^{-34}\\;\\text{J s}$ is Planck's constant."
        ),
        "formal_content": r"\lambda = \frac{h}{p}",
    },
    "Pauli Exclusion Principle": {
        "content": (
            "**Pauli Exclusion Principle**: No two identical fermions can simultaneously "
            "occupy the same quantum state. This explains electron shell structure in atoms "
            "and the stability of matter.\n\n"
            "For fermions: $\\psi(x_1, x_2) = -\\psi(x_2, x_1)$ (antisymmetric under exchange)."
        ),
    },
    "Periodic Law": {
        "content": (
            "**Periodic Law**: The physical and chemical properties of the elements recur "
            "periodically when the elements are arranged in order of increasing atomic "
            "number $Z$. This periodicity arises from electron shell filling governed "
            "by quantum mechanics."
        ),
    },
    "Law of Conservation of Mass": {
        "content": (
            "**Law of Conservation of Mass**: In a closed chemical reaction, the total "
            "mass of the reactants equals the total mass of the products.\n\n"
            "$$\\sum m_{\\text{reactants}} = \\sum m_{\\text{products}}$$\n\n"
            "Note: at relativistic energies this is subsumed by $E = mc^2$."
        ),
    },
    "Avogadro's Law": {
        "content": (
            "**Avogadro's Law**: Equal volumes of all gases, at the same temperature "
            "and pressure, contain the same number of molecules.\n\n"
            "$$\\frac{V}{n} = \\text{const} \\quad (\\text{at fixed } T, P)$$\n\n"
            "where $N_A = 6.022 \\times 10^{23}\\;\\text{mol}^{-1}$ is Avogadro's number."
        ),
        "formal_content": r"\frac{V}{n} = \text{const}; \quad N_A = 6.022 \times 10^{23}\;\text{mol}^{-1}",
    },
    "Chemical Bonding": {
        "content": (
            "**Chemical Bonding**: Atoms bond by:\n\n"
            "- **Covalent** bonding: sharing electrons\n"
            "- **Ionic** bonding: transferring electrons\n"
            "- **Metallic** bonding: pooling electrons\n\n"
            "to achieve more stable electron configurations, typically completing "
            "their valence shell (octet rule)."
        ),
    },
    "Natural Selection": {
        "content": (
            "**Natural Selection**: Organisms with heritable traits better suited to "
            "their environment tend to survive and reproduce at higher rates, leading "
            "to gradual change in the population over generations.\n\n"
            "Fitness $w$ of a genotype determines its representation in the next generation: "
            "$p' = \\frac{p \\cdot w}{\\bar{w}}$"
        ),
    },
    "Universal Common Descent": {
        "content": (
            "**Universal Common Descent**: All life on Earth shares a single common "
            "ancestor (LUCA). The diversity of life arose through speciation and "
            "adaptation over $\\sim 3.8$ billion years of evolution."
        ),
    },
    "Cell Theory": {
        "content": (
            "**Cell Theory**: Three tenets:\n\n"
            "1. All living organisms are composed of one or more **cells**\n"
            "2. The cell is the basic unit of life\n"
            "3. All cells arise from pre-existing cells (*omnis cellula e cellula*)"
        ),
    },
    "Mendel's Law of Segregation": {
        "content": (
            "**Mendel's Law of Segregation**: During gamete formation, the two alleles "
            "for each gene separate so that each gamete carries only one allele.\n\n"
            "For a heterozygote $Aa$: gametes are $A$ or $a$ with equal probability $\\frac{1}{2}$."
        ),
    },
    "Mendel's Law of Independent Assortment": {
        "content": (
            "**Mendel's Law of Independent Assortment**: Genes for different traits assort "
            "independently of one another during gamete formation (assuming genes are on "
            "different chromosomes).\n\n"
            "For dihybrid $AaBb$: gametes $AB$, $Ab$, $aB$, $ab$ each with probability $\\frac{1}{4}$."
        ),
    },
    "DNA Double Helix": {
        "content": (
            "**DNA Double Helix**: DNA consists of two polynucleotide chains wound around "
            "each other in a double helix, with complementary base pairing:\n\n"
            "- Adenine ($A$) pairs with Thymine ($T$)\n"
            "- Guanine ($G$) pairs with Cytosine ($C$)\n\n"
            "Chargaff's rule: $[A] = [T]$ and $[G] = [C]$."
        ),
    },
    "Central Dogma": {
        "content": (
            "**Central Dogma of Molecular Biology**: Genetic information flows:\n\n"
            "$$\\text{DNA} \\xrightarrow{\\text{transcription}} \\text{RNA} "
            "\\xrightarrow{\\text{translation}} \\text{Protein}$$\n\n"
            "DNA is transcribed into mRNA, which is translated into protein by ribosomes."
        ),
    },
    "Fundamental Theorem of Calculus": {
        "content": (
            "**Fundamental Theorem of Calculus**: Differentiation and integration are "
            "inverse operations. If $F$ is an antiderivative of $f$ on $[a,b]$, then:\n\n"
            "$$\\int_a^b f(x)\\,dx = F(b) - F(a)$$\n\n"
            "where $F'(x) = f(x)$."
        ),
        "formal_content": r"\int_a^b f(x)\,dx = F(b) - F(a) \text{ where } F'(x) = f(x)",
    },
    "Pythagorean Theorem": {
        "content": (
            "**Pythagorean Theorem**: In a right triangle, the square of the length "
            "of the hypotenuse equals the sum of the squares of the other two sides.\n\n"
            "$$a^2 + b^2 = c^2$$"
        ),
        "formal_content": r"a^2 + b^2 = c^2",
    },
    "Euler's Identity": {
        "content": (
            "**Euler's Identity**: The most beautiful equation in mathematics, connecting "
            "five fundamental constants — $e$, $i$, $\\pi$, $1$, and $0$:\n\n"
            "$$e^{i\\pi} + 1 = 0$$\n\n"
            "This is a special case of Euler's formula: $e^{ix} = \\cos x + i\\sin x$."
        ),
        "formal_content": r"e^{i\pi} + 1 = 0",
    },
    "Noether's Theorem": {
        "content": (
            "**Noether's Theorem**: Every differentiable symmetry of the action of a "
            "physical system has a corresponding conservation law:\n\n"
            "| Symmetry | Conservation Law |\n"
            "|---|---|\n"
            "| Translational | Momentum $\\vec{p}$ |\n"
            "| Rotational | Angular momentum $\\vec{L}$ |\n"
            "| Time | Energy $E$ |\n\n"
            "Formally, if $\\delta S = 0$ under a continuous transformation, "
            "then $\\frac{dQ}{dt} = 0$ for some conserved charge $Q$."
        ),
    },
}


def match_claim(content: str) -> dict | None:
    """Match a v1 claim's content to its v2 replacement."""
    for prefix, v2 in V2_CLAIMS.items():
        if content.startswith(prefix):
            return v2
    return None


def run(base_url: str) -> None:
    base = f"{base_url}/v1"
    client = httpx.Client()

    # Login
    print("=== Logging in as seed agent ===")
    auth = client.post(
        f"{base}/auth/login",
        json={"email": SEED_AGENT_EMAIL, "password": SEED_AGENT_PASSWORD},
        timeout=TIMEOUT,
    )
    auth.raise_for_status()
    token = auth.json()["access_token"]
    print(f"  Logged in")

    headers = {"Authorization": f"Bearer {token}"}

    # Fetch all claims
    print("\n=== Fetching existing claims ===")
    resp = client.get(f"{base}/claims", params={"limit": 200}, timeout=TIMEOUT)
    resp.raise_for_status()
    claims = resp.json()["items"]
    print(f"  Found {len(claims)} claims")

    # Filter to v1 only
    v1_claims = [c for c in claims if c["version"] == 1]
    print(f"  {len(v1_claims)} are version 1")

    # Create v2 for each
    print("\n=== Creating v2 claims with LaTeX ===")
    updated = 0
    skipped = 0
    for claim in v1_claims:
        v2 = match_claim(claim["content"])
        if v2 is None:
            print(f"  SKIP: no v2 mapping for '{claim['content'][:50]}...'")
            skipped += 1
            continue

        payload = {"content": v2["content"]}
        if v2.get("formal_content"):
            payload["formal_content"] = v2["formal_content"]

        r = client.post(
            f"{base}/claims/{claim['id']}/versions",
            json=payload,
            headers=headers,
            timeout=TIMEOUT,
        )
        if r.status_code == 201:
            new = r.json()
            print(f"  v2 {new['id'][:8]} <- {claim['id'][:8]}: {claim['content'][:40]}...")
            updated += 1
        else:
            print(f"  ERROR {r.status_code}: {r.text[:200]}", file=sys.stderr)

    print(f"\n=== Done: {updated} updated, {skipped} skipped ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update seed claims to v2 with LaTeX")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Phiacta API base URL (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()
    run(args.base_url)
