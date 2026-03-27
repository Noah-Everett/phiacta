---
name: References
slug: references
description: "How references connect entries — structure, dependency, evidence, and interpretation"
---

# References

References are typed, directed links between entries. They capture how knowledge relates: what depends on what, what supports what, what contains what. Together, references form a knowledge graph that makes Phiacta more than a collection of isolated entries.

## When to create references

Create a reference whenever one entry meaningfully relates to another. Common situations:

- A composite entry (paper, argument) contains its component entries
- A theorem uses a definition
- An experimental result supports a theoretical prediction
- One entry corrects or extends another

References are most useful when the relationship is clear and meaningful. Loosely related entries can be connected too, but keep in mind that highly specific references make the knowledge graph easier to navigate.

## Direction

References have a source and a target. Read them as: **"source [role] target."**

- `entry_id` = the source (the entry doing the action)
- `target_entry_id` = the target (the entry being acted upon)

Example: If entry A uses definition B, the source is A and the target is B: "A uses B."

## Roles

Reference roles are **open-ended strings** — use whatever fits. These are the conventional roles:

### Structural

- **contains** — Source is a composite that includes the target. A paper `contains` its theorems.
- **extends** — Source builds on or generalizes the target.

### Dependency

- **uses** — Source depends on or applies the target. A theorem `uses` a definition.
- **assumes** — Source takes the target as given without re-deriving it.

### Evidential

- **supports** — Source provides evidence for the target.
- **contradicts** — Source provides evidence against the target.
- **corrects** — Source fixes an error in the target.

### Interpretive

- **reviews** — Source is a review or commentary on the target.
- **explains** — Source provides a more accessible explanation of the target.
- **applies** — Source applies the target to a specific domain or problem.

These are recommendations, not a closed set. If none of these fit, use a descriptive string that does.
