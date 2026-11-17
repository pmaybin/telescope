# ADR-0004: Pagination

- Status: Accepted
- Date: 2026-11-17

## Context
The API paginates a locally held, sorted, filtered list (ADR-0002). The brief gives no mode. The human chose **cursor by default; offset later if time allows** (decisions log #4). Defaults are limit 30, max 100. The dataset can change between requests (snapshot refresh, ADR-0003).

## Options considered
- **Offset (`offset`/`limit`)**: simple, supports random access and "page 7 of 20". But inserting or deleting rows between requests shifts the window, so rows are skipped or repeated. It is also O(offset) on databases (irrelevant here, as we slice an array).
- **Page (`page`/`per_page`)**: offset with different arithmetic and the same problems. Cut for time (it adds a third mode with no extra capability).
- **Keyset cursor**: continues "strictly after the last item seen", so it is stable under inserts and deletes before the cursor, and bounded cost. It has no random access and a more complex implementation. Chosen as the default.

## Decision
- `cursor` is the default and only mode in v1. `offset` is a stretch bead (tel-offset), mutually exclusive with `cursor` (400 `invalid-pagination` if both). `page/per_page` are cut.
- **Format**: `base64url(JSON)` with no padding, `{"v":1,"q":<query hash>,"s":<snapshot id>,"k":[<sort value>,<id>],"d":"next"|"prev"}`. The sort value is an int, an ISO string or null. The tuple `(sort value, id)` is the keyset position.
- **Query hash (`q`)**: a short sha256 over normalised filters + sort + effective order. `limit` is deliberately excluded, so a client can change page size mid-walk. A mismatch gives 400 `invalid-cursor`, because reusing a cursor under different filters is a client bug, not something to guess at. Malformed base64, JSON, version or shape gives the same 400.
- **Snapshot id (`s`)**: a content hash (sha256 prefix over the repos sorted by id). It is not a timestamp, so a revalidation that changed nothing keeps the id and cursors stay "current".
- **Position lookup**: bisect over the sort-key tuples, not a search for the id. It works even when the cursor's row no longer exists.
- `next_cursor` encodes the last item's key (`d=next`) when more follow. `prev_cursor` encodes the first item's key (`d=prev`) when rows precede it, returning the `limit` items strictly before, in forward order.

## Consistency trade-offs per mode
| Mode | Within one snapshot | Across a snapshot change |
|---|---|---|
| Cursor | Exact: every row once, in order | Continues by keyset, which is well-defined. `snapshot.cursor_from_older_snapshot=true`. Rows whose sort key changed (e.g. stars) may move, appear twice, or be missed. Documented, not hidden |
| Offset (later) | Exact | Window shifts: duplicates and gaps are possible. It carries the same flag semantics |

We chose to continue rather than reject a cursor from an older snapshot: failing every in-flight user at each refresh would be worse than a visible, flagged imperfection.

## Consequences
- Pro: stable, O(log n) positioning. No duplicates or gaps within a snapshot, and robust to row deletion.
- Pro: `total` (filtered count) is still returned, so the UI can say "N of total".
- Con: no jump-to-page and no "page X of Y". This is acceptable for a browse-and-filter list.
- Con: cursors are opaque but not signed. Tampering gives wrong positions for that client only, and nothing is exposed that the client could not query anyway.
- Con: sort-key changes across snapshots can still reorder rows. This is inherent to any keyset scheme on mutable data.
