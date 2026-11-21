# ADR-0012: Progressive cold load (fast provisional first page + load progress)

- Status: Accepted (architect, 2026-11-21; preview cap added after the human asked to minimise GitHub quota)
- Date: 2026-11-21
- Research: `docs/research/cold-load-first-page.md`

## Context
A cold org fetch takes about 7 s (google, with a token) to about 15–33 s (microsoft). Until the last page arrives the request blocks, and the UI shows only a spinner. ADR-0002 (fetch everything, then filter locally) stays correct for every request *after* the first. The problem is only the blank wait on the first one.

Measurements show that for every sort we offer, a single upstream call (about 1 s) returns exactly the same first page as our complete snapshot: list endpoint sorts for `name`/`updated`/`pushed`, and the Search API for `stars`.

## Options considered
1. **Block until the snapshot is complete (today).** Simple and always correct, but 7–33 s of nothing.
2. **Serve results computed from the pages loaded so far.** Correct only for `name asc`, because the pages come in `full_name` order. For `stars` it confidently shows the wrong top 30. Rejected.
3. **202 Accepted plus a job resource the client polls.** Clean REST semantics, but it adds a second resource and client state machine, and gives the user nothing to look at while waiting. Rejected on its own; we keep its "progress" idea.
4. **Server-Sent Events stream of progress, then the result.** Nice UX, but long-lived connections need nginx changes (`proxy_buffering off`), multi-replica fan-out and more test surface. Deferred; a later upgrade path.
5. **Provisional first page plus progress on the same endpoint (chosen).** On a cold miss, the endpoint answers within about 1–1.5 s with an exact *provisional* first page from a cheap upstream "preview" call, plus load progress. The client re-requests the same URL until `snapshot.complete` is true. Re-requests are cheap: they join the single-flight walk and reuse the cached preview.

## Decision
**Backend**
- The snapshot load becomes a **background job** owned by `SnapshotService` (the existing single-flight task), with observable progress: `pages_done` and `pages_total` (known after page 1). The progress lives next to the in-flight task. For Redis it would be stored under `progress:{org}` with a short TTL, so any replica can report it.
- Request path on a cold miss: start or join the job, then wait up to `COLD_WAIT_MS` (default 1500). If the snapshot lands in time, respond exactly as today. Otherwise respond `200` with a provisional page:
  - `snapshot.complete: false` and `snapshot.progress: {pages_done, pages_total}`. In this mode `snapshot.id` is `null`.
  - `items` come from a **PreviewSource** chosen by sort:
    - `name`: list `sort=full_name`.
    - `updated`/`pushed`: list `sort=updated|pushed`.
    - `stars`: Search with filters translated to qualifiers.
  - The list previews are exact only when the local filters leave at least `limit` matches and the ordering under our null rules is guaranteed. Otherwise `items: []` with `page.provisional_reason` set; the UI then shows progress only.
  - `page.next_cursor` and `page.prev_cursor` are `null`, so there is no paging into a dataset that doesn't exist yet. `page.total` comes from Search `total_count` when available, otherwise `null`.
  - Headers: `Cache-Control: no-store`, no `ETag`, and `Retry-After: 1` as the polling hint.
- **Preview cap (human, 2026-11-21: minimise GitHub quota)**: `PREVIEW_MODE=first` (the default) allows **one preview per cold load per org**, serving only the query that triggered the load. Later filter or sort changes during the same load get progress only. When the first query is `sort=name` asc, the preview *is* page 1 of the walk and costs 0 extra calls. `off` behaves exactly as before with zero extra calls (progress only), and `per-query` is the more generous option. Worst case is N + 1 calls per cold org. The preview is cached for the life of the job, so polling costs nothing. Previews are charged to the initiating user's upstream budget (ADR-0013).
- **Quota rules**:
  - A preview counts against the budget guard. A `stars` preview uses the separate Search quota, so it never competes with the core walk.
  - Search is limited to 10 requests/min tokenless. When the Search budget is exhausted, we skip the preview and degrade to progress-only, never to an error.
  - A preview failure never fails the request; only a failure of the walk itself fails it, as today.
- The contract changes are **additive and optional**: `snapshot.complete` defaults to `true`, and `progress` and `provisional_reason` are nullable. Existing clients that ignore them keep working and simply see a short page during a cold load. The OpenAPI spec and generated client are regenerated, and the drift tests cover them.

**Frontend**
- While `snapshot.complete === false`, React Query re-fetches every 1 s, honouring `Retry-After`. Polling stops when the snapshot is complete.
- With provisional items, the table renders them immediately with a slim progress banner, for example "Loading all 2,947 repositories… 12/30 pages", and a progress bar. Next/Prev are disabled with the tooltip "Available once loading finishes". The sort and filter controls stay live.
- With no provisional items, the view shows skeleton rows with the same banner, so the user sees a determinate progress bar instead of a bare spinner.
- When the snapshot completes, rows swap in place. They normally match, because the previews were shown to be exact, so nothing visibly jumps. The banner fades out.

**Independent speed-ups (same branch, separate commits)**
- `PREWARM_ORGS` (comma list) warms these orgs at startup and keeps them warm through SWR.
- `GITHUB_PAGE_CONCURRENCY_AUTHENTICATED` (default 8): reviewers can raise it, documented with the secondary-limit caveat.

## Consequences
- A cold first paint drops from 7–33 s to about 1–1.5 s for typical queries, with a determinate progress bar for the remainder.
- One extra upstream call per distinct cold query. Tokenless users of a 30-page org go from 30 to 31 core requests. A stars preview uses the Search quota instead.
- Provisional data can differ slightly from the final snapshot because of search-index lag. It is labelled as provisional, and the swap reconciles it.
- More states to test: timing (wait deadline hit or missed), preview exact or inexact, preview failure, Search budget exhausted, and polling stopping on completion. Tests use the existing injected clock, respx previews and a blocking fake fetcher (ADR-0011).
- SSE (option 4) remains a drop-in upgrade later. The response shape would be the same and only the transport would change.
