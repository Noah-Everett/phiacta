---
name: Reference Roles
slug: reference-roles
description: "Available reference relationship types (contains, uses, supports, etc.) and when to use each"
---

# Reference Roles

References connect entries with typed relationships. Use the `create_reference` tool with the `rel` field set to one of the roles below.

## Structural roles

- **contains** — The source entry is a composite that includes the target as a component. Example: a paper entry `contains` each theorem, definition, and result entry extracted from it.
- **extends** — The source builds on or generalizes the target. Example: a theorem that generalizes a prior result.

## Dependency roles

- **uses** — The source depends on or applies the target. Example: a theorem that uses a definition, or a result that uses a specific method.
- **assumes** — The source takes the target as a given without re-deriving it.

## Evidential roles

- **supports** — The source provides evidence for the target. Example: an experimental result that supports a theoretical prediction.
- **contradicts** — The source provides evidence against the target.
- **corrects** — The source fixes an error in the target.

## Interpretive roles

- **reviews** — The source is a review or commentary on the target.
- **explains** — The source provides an accessible explanation of the target.
- **applies** — The source applies the target to a specific domain or problem.

## Choosing the right role

The reference direction matters: `entry_id` is the source (the entry "doing" the action), `target_entry_id` is the target. Read it as: "source [role] target."

Example: If theorem A uses definition B, create the reference with `entry_id=A, target_entry_id=B, rel="uses"`.
