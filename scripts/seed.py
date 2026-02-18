#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Phiacta Contributors
"""Seed the Phiacta database with foundational science claims via the REST API.

Usage:
    python scripts/seed.py                           # defaults to https://phiacta.com
    python scripts/seed.py --base-url http://localhost:8000
    PHIACTA_SEED_PASSWORD=supersecret python scripts/seed.py
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://api.phiacta.com"
SEED_AGENT_NAME = "seed-agent"
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
            # Known issue: dispatch_event fails due to missing extensions table,
            # but the data is already committed before the error.
            print(f"  WARN: got 500 (data likely committed anyway)", file=sys.stderr)
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

NAMESPACES = {
    "science": {
        "name": "science",
        "description": "Root namespace for all scientific knowledge",
    },
    "physics": {
        "name": "physics",
        "description": "Classical and modern physics",
        "parent": "science",
    },
    "classical-mechanics": {
        "name": "classical-mechanics",
        "description": "Newtonian mechanics and related topics",
        "parent": "physics",
    },
    "thermodynamics": {
        "name": "thermodynamics",
        "description": "Heat, energy, and entropy",
        "parent": "physics",
    },
    "electromagnetism": {
        "name": "electromagnetism",
        "description": "Electric and magnetic fields, Maxwell's equations",
        "parent": "physics",
    },
    "relativity": {
        "name": "relativity",
        "description": "Special and general relativity",
        "parent": "physics",
    },
    "quantum-mechanics": {
        "name": "quantum-mechanics",
        "description": "Quantum theory and wave mechanics",
        "parent": "physics",
    },
    "chemistry": {
        "name": "chemistry",
        "description": "Chemical elements, reactions, and bonding",
        "parent": "science",
    },
    "biology": {
        "name": "biology",
        "description": "Life sciences",
        "parent": "science",
    },
    "genetics": {
        "name": "genetics",
        "description": "Heredity and molecular genetics",
        "parent": "biology",
    },
    "evolution": {
        "name": "evolution",
        "description": "Evolutionary biology and natural selection",
        "parent": "biology",
    },
    "mathematics": {
        "name": "mathematics",
        "description": "Pure and applied mathematics",
        "parent": "science",
    },
    "calculus": {
        "name": "calculus",
        "description": "Differential and integral calculus",
        "parent": "mathematics",
    },
}

SOURCES = [
    {
        "key": "principia",
        "source_type": "paper",
        "title": "Philosophiae Naturalis Principia Mathematica",
        "external_ref": "Newton, I. (1687)",
        "attrs": {"author": "Isaac Newton", "year": 1687},
    },
    {
        "key": "origin",
        "source_type": "paper",
        "title": "On the Origin of Species",
        "external_ref": "Darwin, C. (1859)",
        "attrs": {"author": "Charles Darwin", "year": 1859},
    },
    {
        "key": "einstein_sr",
        "source_type": "paper",
        "title": "On the Electrodynamics of Moving Bodies",
        "external_ref": "Einstein, A. (1905). Annalen der Physik, 17, 891-921",
        "attrs": {"author": "Albert Einstein", "year": 1905},
    },
    {
        "key": "einstein_gr",
        "source_type": "paper",
        "title": "The Foundation of the General Theory of Relativity",
        "external_ref": "Einstein, A. (1916). Annalen der Physik, 49, 769-822",
        "attrs": {"author": "Albert Einstein", "year": 1916},
    },
    {
        "key": "maxwell",
        "source_type": "paper",
        "title": "A Dynamical Theory of the Electromagnetic Field",
        "external_ref": "Maxwell, J.C. (1865). Philosophical Transactions, 155, 459-512",
        "attrs": {"author": "James Clerk Maxwell", "year": 1865},
    },
    {
        "key": "schrodinger",
        "source_type": "paper",
        "title": "Quantisation as an Eigenvalue Problem",
        "external_ref": "Schrodinger, E. (1926). Annalen der Physik, 79, 361-376",
        "attrs": {"author": "Erwin Schrodinger", "year": 1926},
    },
    {
        "key": "watson_crick",
        "source_type": "paper",
        "title": "Molecular Structure of Nucleic Acids",
        "external_ref": "Watson, J.D. & Crick, F.H.C. (1953). Nature, 171, 737-738",
        "attrs": {"author": "James Watson & Francis Crick", "year": 1953},
    },
    {
        "key": "mendeleev",
        "source_type": "paper",
        "title": "The Relation between the Properties and Atomic Weights of the Elements",
        "external_ref": "Mendeleev, D. (1869). Journal of the Russian Chemical Society, 1, 60-77",
        "attrs": {"author": "Dmitri Mendeleev", "year": 1869},
    },
    {
        "key": "carnot",
        "source_type": "paper",
        "title": "Reflections on the Motive Power of Fire",
        "external_ref": "Carnot, S. (1824)",
        "attrs": {"author": "Sadi Carnot", "year": 1824},
    },
    {
        "key": "mendel",
        "source_type": "paper",
        "title": "Experiments on Plant Hybridization",
        "external_ref": "Mendel, G. (1866). Verhandlungen des naturforschenden Vereines in Brunn, 4, 3-47",
        "attrs": {"author": "Gregor Mendel", "year": 1866},
    },
    {
        "key": "newton_leibniz",
        "source_type": "paper",
        "title": "Nova Methodus pro Maximis et Minimis",
        "external_ref": "Leibniz, G.W. (1684). Acta Eruditorum",
        "attrs": {"author": "Gottfried Wilhelm Leibniz", "year": 1684},
    },
]

# Claims: keyed for later relation references
# claim_type values: assertion, evidence, theorem, proof, definition, law, hypothesis
CLAIMS = [
    # -- Classical Mechanics --
    {
        "key": "newton_1",
        "namespace": "classical-mechanics",
        "claim_type": "law",
        "content": "Newton's First Law: An object at rest stays at rest, and an object in motion stays in uniform motion, unless acted upon by a net external force.",
        "formal_content": "If F_net = 0, then dv/dt = 0",
    },
    {
        "key": "newton_2",
        "namespace": "classical-mechanics",
        "claim_type": "law",
        "content": "Newton's Second Law: The acceleration of an object is directly proportional to the net force acting on it and inversely proportional to its mass.",
        "formal_content": "F = ma (or equivalently, F = dp/dt)",
    },
    {
        "key": "newton_3",
        "namespace": "classical-mechanics",
        "claim_type": "law",
        "content": "Newton's Third Law: For every action, there is an equal and opposite reaction. When object A exerts a force on object B, object B simultaneously exerts an equal and opposite force on object A.",
        "formal_content": "F_AB = -F_BA",
    },
    {
        "key": "conservation_energy",
        "namespace": "classical-mechanics",
        "claim_type": "law",
        "content": "Law of Conservation of Energy: Energy cannot be created or destroyed in an isolated system; it can only be transformed from one form to another. The total energy of an isolated system remains constant.",
        "formal_content": "dE/dt = 0 for isolated systems",
    },
    {
        "key": "conservation_momentum",
        "namespace": "classical-mechanics",
        "claim_type": "theorem",
        "content": "Conservation of Linear Momentum: In a closed system with no external forces, the total linear momentum is conserved. This follows from Newton's Third Law.",
        "formal_content": "If F_ext = 0, then dp_total/dt = 0",
    },
    {
        "key": "universal_gravitation",
        "namespace": "classical-mechanics",
        "claim_type": "law",
        "content": "Newton's Law of Universal Gravitation: Every particle of matter attracts every other particle with a force proportional to the product of their masses and inversely proportional to the square of the distance between them.",
        "formal_content": "F = G * m1 * m2 / r^2",
    },
    # -- Thermodynamics --
    {
        "key": "thermo_0",
        "namespace": "thermodynamics",
        "claim_type": "law",
        "content": "Zeroth Law of Thermodynamics: If two thermodynamic systems are each in thermal equilibrium with a third system, they are in thermal equilibrium with each other. This establishes temperature as a fundamental measurable property.",
    },
    {
        "key": "thermo_1",
        "namespace": "thermodynamics",
        "claim_type": "law",
        "content": "First Law of Thermodynamics: The change in internal energy of a closed system equals the heat added to the system minus the work done by the system.",
        "formal_content": "dU = dQ - dW",
    },
    {
        "key": "thermo_2",
        "namespace": "thermodynamics",
        "claim_type": "law",
        "content": "Second Law of Thermodynamics: In any cyclic process, the total entropy of an isolated system can only increase over time. Heat cannot spontaneously flow from a colder body to a hotter body.",
        "formal_content": "dS >= dQ/T (equality for reversible processes)",
    },
    {
        "key": "thermo_3",
        "namespace": "thermodynamics",
        "claim_type": "law",
        "content": "Third Law of Thermodynamics: As the temperature of a system approaches absolute zero, the entropy of the system approaches a minimum value (zero for a perfect crystal).",
        "formal_content": "lim(T->0) S = 0 for perfect crystals",
    },
    # -- Electromagnetism --
    {
        "key": "maxwell_equations",
        "namespace": "electromagnetism",
        "claim_type": "law",
        "content": "Maxwell's Equations: Four partial differential equations that together form the foundation of classical electromagnetism, describing how electric and magnetic fields are generated by charges, currents, and changes of each other.",
        "formal_content": "div E = rho/epsilon_0; div B = 0; curl E = -dB/dt; curl B = mu_0*J + mu_0*epsilon_0*dE/dt",
    },
    {
        "key": "coulombs_law",
        "namespace": "electromagnetism",
        "claim_type": "law",
        "content": "Coulomb's Law: The electrostatic force between two point charges is directly proportional to the product of their charges and inversely proportional to the square of the distance between them.",
        "formal_content": "F = k_e * q1 * q2 / r^2",
    },
    {
        "key": "em_wave_prediction",
        "namespace": "electromagnetism",
        "claim_type": "theorem",
        "content": "Maxwell's equations predict the existence of electromagnetic waves propagating at the speed of light. This unifies optics with electromagnetism and shows that light is an electromagnetic wave.",
        "formal_content": "c = 1/sqrt(mu_0 * epsilon_0)",
    },
    # -- Relativity --
    {
        "key": "special_relativity",
        "namespace": "relativity",
        "claim_type": "law",
        "content": "Special Relativity: The laws of physics are the same in all inertial reference frames. The speed of light in vacuum is constant for all observers regardless of their relative motion.",
    },
    {
        "key": "mass_energy",
        "namespace": "relativity",
        "claim_type": "theorem",
        "content": "Mass-Energy Equivalence: Energy and mass are interchangeable. A body at rest has an intrinsic energy proportional to its mass.",
        "formal_content": "E = mc^2",
    },
    {
        "key": "time_dilation",
        "namespace": "relativity",
        "claim_type": "theorem",
        "content": "Time Dilation: A clock moving relative to an observer ticks more slowly than a clock at rest with respect to that observer. Time intervals are frame-dependent.",
        "formal_content": "dt' = dt * sqrt(1 - v^2/c^2)",
    },
    {
        "key": "general_relativity",
        "namespace": "relativity",
        "claim_type": "law",
        "content": "General Relativity: Gravity is not a force but a manifestation of spacetime curvature caused by mass and energy. Massive objects cause spacetime to curve, and free-falling objects follow geodesics in this curved spacetime.",
        "formal_content": "G_mu_nu + Lambda*g_mu_nu = (8*pi*G/c^4) * T_mu_nu",
    },
    # -- Quantum Mechanics --
    {
        "key": "schrodinger_eq",
        "namespace": "quantum-mechanics",
        "claim_type": "law",
        "content": "Schrodinger Equation: The fundamental equation of quantum mechanics that describes how the quantum state of a physical system changes over time.",
        "formal_content": "i*hbar * d|psi>/dt = H|psi>",
    },
    {
        "key": "heisenberg_uncertainty",
        "namespace": "quantum-mechanics",
        "claim_type": "theorem",
        "content": "Heisenberg Uncertainty Principle: It is impossible to simultaneously know both the exact position and exact momentum of a particle. The product of the uncertainties has a fundamental lower bound.",
        "formal_content": "delta_x * delta_p >= hbar/2",
    },
    {
        "key": "wave_particle_duality",
        "namespace": "quantum-mechanics",
        "claim_type": "assertion",
        "content": "Wave-Particle Duality: Quantum entities exhibit both wave-like and particle-like properties. The de Broglie relation connects a particle's momentum to its wavelength.",
        "formal_content": "lambda = h/p",
    },
    {
        "key": "pauli_exclusion",
        "namespace": "quantum-mechanics",
        "claim_type": "law",
        "content": "Pauli Exclusion Principle: No two identical fermions can simultaneously occupy the same quantum state. This explains electron shell structure in atoms and the stability of matter.",
    },
    # -- Chemistry --
    {
        "key": "periodic_law",
        "namespace": "chemistry",
        "claim_type": "law",
        "content": "Periodic Law: The physical and chemical properties of the elements recur periodically when the elements are arranged in order of increasing atomic number.",
    },
    {
        "key": "law_conservation_mass",
        "namespace": "chemistry",
        "claim_type": "law",
        "content": "Law of Conservation of Mass: In a closed chemical reaction, the total mass of the reactants equals the total mass of the products. Matter is neither created nor destroyed.",
    },
    {
        "key": "avogadro",
        "namespace": "chemistry",
        "claim_type": "law",
        "content": "Avogadro's Law: Equal volumes of all gases, at the same temperature and pressure, contain the same number of molecules.",
        "formal_content": "V/n = constant (at fixed T, P); N_A = 6.022 x 10^23 mol^-1",
    },
    {
        "key": "chemical_bonding",
        "namespace": "chemistry",
        "claim_type": "assertion",
        "content": "Chemical Bonding: Atoms bond by sharing (covalent), transferring (ionic), or pooling (metallic) electrons to achieve more stable electron configurations, typically completing their valence shell.",
    },
    # -- Biology / Evolution --
    {
        "key": "natural_selection",
        "namespace": "evolution",
        "claim_type": "law",
        "content": "Natural Selection: Organisms with heritable traits better suited to their environment tend to survive and reproduce at higher rates, leading to gradual change in the population over generations.",
    },
    {
        "key": "common_descent",
        "namespace": "evolution",
        "claim_type": "assertion",
        "content": "Universal Common Descent: All life on Earth shares a single common ancestor. The diversity of life arose through speciation and adaptation over billions of years.",
    },
    {
        "key": "cell_theory",
        "namespace": "biology",
        "claim_type": "law",
        "content": "Cell Theory: All living organisms are composed of one or more cells. The cell is the basic unit of life. All cells arise from pre-existing cells.",
    },
    # -- Genetics --
    {
        "key": "mendel_segregation",
        "namespace": "genetics",
        "claim_type": "law",
        "content": "Mendel's Law of Segregation: During gamete formation, the two alleles for each gene separate so that each gamete carries only one allele for each trait.",
    },
    {
        "key": "mendel_independent",
        "namespace": "genetics",
        "claim_type": "law",
        "content": "Mendel's Law of Independent Assortment: Genes for different traits assort independently of one another during gamete formation (assuming genes are on different chromosomes).",
    },
    {
        "key": "dna_structure",
        "namespace": "genetics",
        "claim_type": "evidence",
        "content": "DNA Double Helix: DNA consists of two polynucleotide chains wound around each other in a double helix, with complementary base pairing (A-T, G-C) holding the strands together.",
        "verification_code": "# Chargaff's rule verification\nA = 30.9  # % adenine (human DNA)\nT = 29.4  # % thymine\nG = 19.9  # % guanine\nC = 19.8  # % cytosine\nassert abs(A - T) < 2.0, f'A ({A}) should roughly equal T ({T})'\nassert abs(G - C) < 2.0, f'G ({G}) should roughly equal C ({C})'\nprint(f'A/T ratio: {A/T:.3f} (expected ~1.0)')\nprint(f'G/C ratio: {G/C:.3f} (expected ~1.0)')\nprint('Chargaffs rules verified')",
        "verification_runner_type": "python_script",
    },
    {
        "key": "central_dogma",
        "namespace": "genetics",
        "claim_type": "assertion",
        "content": "Central Dogma of Molecular Biology: Genetic information flows from DNA to RNA to protein. DNA is transcribed into mRNA, which is translated into protein by ribosomes.",
    },
    # -- Mathematics --
    {
        "key": "ftc",
        "namespace": "calculus",
        "claim_type": "theorem",
        "content": "Fundamental Theorem of Calculus: Differentiation and integration are inverse operations. If F is an antiderivative of f on [a,b], then the definite integral of f from a to b equals F(b) - F(a).",
        "formal_content": "integral(a,b) f(x)dx = F(b) - F(a) where F'(x) = f(x)",
    },
    {
        "key": "pythagorean",
        "namespace": "mathematics",
        "claim_type": "theorem",
        "content": "Pythagorean Theorem: In a right triangle, the square of the length of the hypotenuse equals the sum of the squares of the other two sides.",
        "formal_content": "a^2 + b^2 = c^2",
    },
    {
        "key": "euler_identity",
        "namespace": "mathematics",
        "claim_type": "theorem",
        "content": "Euler's Identity: The most beautiful equation in mathematics, connecting five fundamental constants: e, i, pi, 1, and 0.",
        "formal_content": "e^(i*pi) + 1 = 0",
    },
    {
        "key": "noether",
        "namespace": "mathematics",
        "claim_type": "theorem",
        "content": "Noether's Theorem: Every differentiable symmetry of the action of a physical system has a corresponding conservation law. Translational symmetry yields conservation of momentum; rotational symmetry yields conservation of angular momentum; time symmetry yields conservation of energy.",
    },
]

# Relations between claims: (source_key, target_key, relation_type, strength)
RELATIONS = [
    # Newton's laws form a unified framework
    ("newton_2", "newton_1", "generalizes", 0.9),
    ("newton_3", "conservation_momentum", "derives", 1.0),
    ("newton_2", "universal_gravitation", "supports", 0.8),

    # Thermodynamics connections
    ("thermo_1", "conservation_energy", "specializes", 0.95),
    ("thermo_2", "thermo_1", "extends", 0.8),
    ("thermo_3", "thermo_2", "extends", 0.7),

    # Electromagnetism
    ("maxwell_equations", "coulombs_law", "generalizes", 0.95),
    ("maxwell_equations", "em_wave_prediction", "derives", 1.0),

    # Relativity supersedes / extends classical mechanics
    ("special_relativity", "newton_1", "generalizes", 0.9),
    ("special_relativity", "newton_2", "generalizes", 0.9),
    ("mass_energy", "special_relativity", "derives", 1.0),
    ("time_dilation", "special_relativity", "derives", 1.0),
    ("general_relativity", "special_relativity", "generalizes", 0.95),
    ("general_relativity", "universal_gravitation", "generalizes", 0.95),

    # Quantum mechanics
    ("heisenberg_uncertainty", "schrodinger_eq", "derives", 0.9),
    ("wave_particle_duality", "schrodinger_eq", "supports", 0.85),
    ("pauli_exclusion", "schrodinger_eq", "derives", 0.8),

    # QM explains chemistry
    ("pauli_exclusion", "chemical_bonding", "supports", 0.9),
    ("pauli_exclusion", "periodic_law", "supports", 0.85),

    # Biology / Genetics
    ("natural_selection", "common_descent", "supports", 0.95),
    ("mendel_segregation", "natural_selection", "supports", 0.8),
    ("mendel_independent", "mendel_segregation", "extends", 0.7),
    ("dna_structure", "mendel_segregation", "supports", 0.9),
    ("dna_structure", "central_dogma", "supports", 1.0),

    # Cross-domain: Noether connects symmetry to conservation laws
    ("noether", "conservation_energy", "derives", 1.0),
    ("noether", "conservation_momentum", "derives", 1.0),

    # Chemistry <-> Physics
    ("conservation_energy", "law_conservation_mass", "related_to", 0.7),
    ("mass_energy", "law_conservation_mass", "generalizes", 0.8),

    # EM waves and QM
    ("em_wave_prediction", "wave_particle_duality", "related_to", 0.75),
]


# ---------------------------------------------------------------------------
# Seed runner
# ---------------------------------------------------------------------------


def seed(base_url: str) -> None:
    base = api(base_url)
    client = httpx.Client()

    # ── 1. Register & login ────────────────────────────────────────────
    print("=== Registering seed agent ===")
    try:
        auth = post(client, f"{base}/auth/register", {
            "name": SEED_AGENT_NAME,
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

    # ── 2. Create or fetch namespaces ─────────────────────────────────
    print("\n=== Creating namespaces ===")
    ns_ids: dict[str, str] = {}

    # Fetch existing namespaces first
    existing_ns = get(client, f"{base}/namespaces", token=token, params={"limit": 200})
    existing_ns_by_name = {n["name"]: n["id"] for n in existing_ns.get("items", [])}

    for key, ns in NAMESPACES.items():
        if ns["name"] in existing_ns_by_name:
            ns_ids[key] = existing_ns_by_name[ns["name"]]
            print(f"  {key}: {ns_ids[key]} (exists)")
            continue
        payload: dict = {"name": ns["name"], "description": ns.get("description")}
        parent_key = ns.get("parent")
        if parent_key and parent_key in ns_ids:
            payload["parent_id"] = ns_ids[parent_key]
        resp = post(client, f"{base}/namespaces", payload, token=token)
        ns_ids[key] = resp["id"]
        parent_info = f" (parent: {parent_key})" if parent_key else ""
        print(f"  {key}: {resp['id']}{parent_info}")

    # ── 3. Create sources ──────────────────────────────────────────────
    print("\n=== Creating sources ===")
    src_ids: dict[str, str] = {}

    # Fetch existing sources
    existing_src = get(client, f"{base}/sources", token=token, params={"limit": 200})
    existing_src_by_title = {s["title"]: s["id"] for s in existing_src.get("items", [])}

    for src in SOURCES:
        if src["title"] in existing_src_by_title:
            src_ids[src["key"]] = existing_src_by_title[src["title"]]
            print(f"  {src['key']}: {src_ids[src['key']]} (exists)")
            continue
        payload = {
            "source_type": src["source_type"],
            "title": src["title"],
            "external_ref": src.get("external_ref"),
            "attrs": src.get("attrs", {}),
        }
        resp = post(client, f"{base}/sources", payload, token=token)
        src_ids[src["key"]] = resp["id"]
        print(f"  {src['key']}: {resp['id']}")

    # ── 4. Create claims ───────────────────────────────────────────────
    # Note: claim creation may return 500 due to missing extensions table
    # (dispatch_event fails), but the claim IS committed before that error.
    # We use tolerate_500=True and then fetch claims back to get IDs.
    print("\n=== Creating claims ===")
    claim_ids: dict[str, str] = {}
    claims_need_lookup: list[dict] = []

    # Fetch existing claims to skip duplicates
    existing_claims_resp = get(client, f"{base}/claims", token=token, params={"limit": 200})
    existing_content_to_id = {c["content"]: c["id"] for c in existing_claims_resp.get("items", [])}

    for cl in CLAIMS:
        if cl["content"] in existing_content_to_id:
            claim_ids[cl["key"]] = existing_content_to_id[cl["content"]]
            print(f"  {cl['key']}: {claim_ids[cl['key']]} (exists)")
            continue
        ns_key = cl["namespace"]
        payload: dict = {
            "content": cl["content"],
            "claim_type": cl["claim_type"],
            "namespace_id": ns_ids[ns_key],
        }
        if cl.get("formal_content"):
            payload["formal_content"] = cl["formal_content"]
        if cl.get("verification_code"):
            payload["verification_code"] = cl["verification_code"]
            payload["verification_runner_type"] = cl.get("verification_runner_type", "python_script")
        resp = post(client, f"{base}/claims", payload, token=token, tolerate_500=True)
        if resp is not None:
            claim_ids[cl["key"]] = resp["id"]
            print(f"  {cl['key']}: {resp['id']}")
        else:
            claims_need_lookup.append(cl)
            print(f"  {cl['key']}: (committed, will look up)")

    # Fetch all claims to resolve IDs for any that returned 500
    if claims_need_lookup:
        print(f"\n  Resolving {len(claims_need_lookup)} claim IDs...")
        all_claims_resp = get(
            client, f"{base}/claims", token=token, params={"limit": 200}
        )
        all_claims = all_claims_resp.get("items", [])
        # Build content -> id lookup
        content_to_id = {c["content"]: c["id"] for c in all_claims}
        for cl in claims_need_lookup:
            cid = content_to_id.get(cl["content"])
            if cid:
                claim_ids[cl["key"]] = cid
                print(f"  {cl['key']}: {cid} (resolved)")
            else:
                print(f"  {cl['key']}: FAILED - not found in database!", file=sys.stderr)

    # ── 5. Create relations ────────────────────────────────────────────
    print("\n=== Creating relations ===")
    for src_key, tgt_key, rel_type, strength in RELATIONS:
        payload = {
            "source_id": claim_ids[src_key],
            "target_id": claim_ids[tgt_key],
            "relation_type": rel_type,
            "created_by": agent_id,
            "strength": strength,
        }
        resp = post(client, f"{base}/relations", payload, token=token)
        print(f"  {src_key} --[{rel_type} ({strength})]-> {tgt_key}: {resp['id']}")

    # ── Summary ────────────────────────────────────────────────────────
    print("\n=== Seed complete ===")
    print(f"  Namespaces: {len(ns_ids)}")
    print(f"  Sources:    {len(src_ids)}")
    print(f"  Claims:     {len(claim_ids)}")
    print(f"  Relations:  {len(RELATIONS)}")
    print(f"\n  Agent: {SEED_AGENT_EMAIL} / {SEED_AGENT_PASSWORD}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Phiacta with foundational science claims")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Phiacta API base URL (default: {DEFAULT_BASE_URL})",
    )
    args = parser.parse_args()
    seed(args.base_url)
