---
name: Getting Started
slug: content-guide
description: "Start here — how entries work, how to structure content, and tips for making entries useful"
---

# Content Writing Guide

This guide covers how to write entry content — the part readers interact with most directly.

## Entries and structure

An entry can represent anything — a single theorem, a full paper, a dataset, a method, a comparison. There's no single right granularity. Two common approaches:

- **Atomic entries** — one idea per entry. A definition, a theorem, a single experimental result. These are highly reusable and easy to reference from other entries.
- **Composite entries** — a paper, a chapter, or an argument that ties together multiple ideas. These reference their component entries using `contains` or `uses` references.

Both are valid. You can publish a paper as a single entry, or decompose it into atomic entries and create a composite entry that links them together. Mix and match however makes sense for the material.

## Tips for readability

These are suggestions, not rules — write in whatever style fits your content.

- **A little context goes a long way.** Readers might arrive via search or a link from another entry. A sentence or two at the top explaining what the entry is about helps them orient themselves.
- **Gloss terms on first use.** When referencing a concept that has its own entry, a brief inline explanation plus a link helps readers who aren't familiar: "measured by [SQNR](/entries/{id}) (signal-to-quantization-noise ratio — higher means less distortion)."
- **Descriptive titles help with discovery.** "Minimax optimality of log-uniform quantization" is easier to find and understand than "Theorem 2.1."

## Knowledge, not documents

When decomposing a source into entries, it helps to write each entry as if the source document doesn't exist:

- **Prefer descriptive titles over document numbering.** If you want to preserve the original numbering for traceability, consider including it alongside a descriptive title.
- **Prefer linking to specific entries over section references.** "See Section 3" doesn't help a reader who doesn't have the source open. Link to the entry that contains the result instead.
- **Summaries tend to be more useful when they describe the knowledge itself.** For example, "Log-uniform quantization minimizes worst-case NMSE over all distributions" works better as a standalone summary than "The paper's main theorem proves that..." which requires knowing which paper.
- **Definitions are often most reusable when written in full generality.** If a concept has a domain-specific meaning, consider noting that alongside the general definition so the entry is useful to a wider audience.
- **Results tend to be most useful when presented as independent, reproducible findings.** Capturing the source via a `contains` reference preserves provenance while keeping the entry's content focused on the result itself.

None of this applies if you're publishing a paper or document as a single entry — in that case, the content is the document itself.

## Provenance

The relationship between a source and its entries is captured by references — typically a `contains` reference from the source to each component entry. That's provenance: where this knowledge was established.

The entry's content is the knowledge itself. Other sources may cite the same entry. A definition entry might be referenced by entries from ten different papers.

## Using files

Every entry is backed by a git repository. Files are a core part of what makes an entry valuable — a theorem entry with a Lean proof attached, a result entry with the raw data and analysis script, a method entry with a reference implementation.

Verification support (formal proofs in Lean, Coq, etc.) is coming soon as a platform extension. In the meantime, you can attach proof files to entries and they'll be ready for verification when the feature lands.

See the [files guide](/guides/files) for details on what to attach and how.
