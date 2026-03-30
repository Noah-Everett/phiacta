---
name: Entry Lifecycle
slug: entry-lifecycle
description: "Status, archiving, edit proposals, and issues — how entries change over time"
---

# Entry Lifecycle

Entries are versioned and immutable in the git sense — every change is a commit. But they go through a lifecycle of status changes, edits, and discussion.

## Status

- **active** — The default state. The entry is visible, searchable, and citable.
- **archived** — Only visible to the entry's owner. For everyone else, the entry behaves as if it doesn't exist (returns 404). References to archived entries still exist as records, but the target entry is hidden from non-owners. Archived entries are excluded from search results, graph traversals, and tag lookups for non-owners.

## Archiving pattern

When creating a group of related entries (e.g., ingesting a paper), a common pattern is:

1. Create the top-level entry and **archive** it immediately.
2. Create all component entries and wire references.
3. **Unarchive** the top-level entry once everything is connected.

This prevents users from seeing a half-built structure.

## Archive visibility rules

- **Direct access** (`GET /entries/{id}`) — Returns 404 for non-owners.
- **Listings** (`GET /entries?status=all`) — Archived entries only appear for their owner.
- **Search** — Archived entries are excluded for non-owners, even with `status=all`.
- **Graph traversal** — Archived entries are not traversed or returned as nodes for non-owners.
- **Tag search** — Archived entries are excluded for non-owners, even with `include_archived=true`.
- **Files, history, edits, issues** — All sub-resources of an archived entry return 404 for non-owners.
- **References** — Reference records persist (the relationship is not deleted), but the target entry's data is hidden. Attempting to follow a reference to an archived entry you don't own returns 404.
- **Entity resolve** — Returns 404 for archived entries the caller doesn't own.

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
