---
name: Content Writing Guide
slug: content-guide
description: "How to write entry content: standalone readability, knowledge identity, linking, file attachments"
---

# Content Writing Guide

Every Phiacta entry must be understandable on its own. A reader may arrive at any entry via search without having seen the source document or any other entry.

## Standalone readability

- **Open with context.** The first 1–2 sentences should explain what this entry is about and why it matters, in plain language that orients a cold reader.
- **Gloss technical terms inline.** The first time you use a concept defined in another entry, briefly explain it in parentheses AND link to the entry. Example: "the [NMSE](/entries/{id}) (normalized mean squared error — the fraction of signal power lost to quantization)."
- **Link, don't re-derive.** Use markdown links `[descriptive text](/entries/{id})` to other Phiacta entries for depth. The link text should provide enough context that the sentence is meaningful even if the reader doesn't click through.

## Knowledge identity, not document identity

Entries represent knowledge — facts, theorems, definitions, results — not sections of a document. Write each entry as if the source document doesn't exist:

- **No document-specific numbering in titles.** Write "Minimax NMSE Optimality of Log-Uniform Quantization", not "Theorem 2.1: Minimax NMSE Optimality..." The source document's numbering scheme is meaningless outside that document.
- **No section references in content.** Write "as shown in the [product error decomposition](/entries/{id})" not "as shown in Section 3". Link to the entry that contains the result.
- **Summaries should be source-agnostic.** Describe the result itself, not its role in a paper. "Log-uniform quantization uniquely minimizes worst-case NMSE over all densities" not "The paper's central theorem proves that..."
- **Definitions should be general-purpose.** If the source defines a mathematical object, define it in full generality, then *mention* that a specific project uses it — don't frame the whole entry around one source.
- **Results should stand as independent findings.** Present empirical results as independently verifiable measurements, with the source as provenance (via a `contains` reference), not their identity.

## Provenance vs. identity

The source document `contains` the entry — that's provenance, captured by a reference. But the entry's *content* should be written as universal knowledge that happens to have been established (or formalized, or measured) in that source. Future entries from other sources may reference the same atomic entries.

## File attachments

Entries can have files attached (proofs, code, data, analysis notes). Use descriptive paths: `proofs/theorem.lean`, `src/implementation.py`, `results/benchmark-data.md`. Plan which files belong to which entries during the planning phase, not as an afterthought.
