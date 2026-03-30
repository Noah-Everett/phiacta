---
name: Entry Lifecycle
slug: entry-lifecycle
description: "Visibility, edit proposals, and issues — how entries change over time"
---

# Entry Lifecycle

Entries are versioned and immutable in the git sense — every change is a commit. But they go through a lifecycle of visibility changes, edits, and discussion.

## Visibility

Every entry has a `visibility` field: **public** or **private**.

- **public** (default) — Visible to everyone. Searchable, citable, and appears in listings.
- **private** — Only visible to the entry's owner. For everyone else, the entry behaves as if it doesn't exist (returns 404). Private entries are excluded from search results, graph traversals, and tag lookups for non-owners.

Set visibility via the update endpoint: `PATCH /entries/{id}` with `{"visibility": "private"}` or `{"visibility": "public"}`.

## Private entry pattern

When creating a group of related entries (e.g., ingesting a paper), a common pattern is:

1. Create the top-level entry and set it to **private** immediately.
2. Create all component entries and wire references.
3. Set the top-level entry to **public** once everything is connected.

This prevents users from seeing a half-built structure.

## Private entry visibility rules

- **Direct access** (`GET /entries/{id}`) — Returns 404 for non-owners.
- **Listings** (`GET /entries?visibility=all`) — Private entries only appear for their owner.
- **Search** — Private entries are excluded for non-owners.
- **Graph traversal** — Private entries are not traversed or returned as nodes for non-owners.
- **Tag search** — Private entries are excluded for non-owners.
- **Files, history, edits, issues** — All sub-resources of a private entry return 404 for non-owners.
- **References** — Reference records persist (the relationship is not deleted), but the target entry's data is hidden. Attempting to follow a reference to a private entry you don't own returns 404.
- **Entity resolve** — Returns 404 for private entries the caller doesn't own.

## Edit proposals

Edit proposals are the mechanism for suggesting changes to entries you don't own. They work like pull requests:

1. Create an edit proposal on an entry, describing the change.
2. The entry owner reviews and either merges or closes it.

Use edit proposals for corrections, improvements, or additions to existing entries.

## Issues

Issues are for flagging problems or starting discussion about an entry:

- Factual errors or inaccuracies
- Missing information or context
- Broken references or outdated content
- Suggestions for improvement

Issues are lighter-weight than edit proposals — they describe a problem without proposing a specific fix.
