# API contract: `GET /api/orgs/{org}/repos`

Status: draft v1 (architect). `backend/openapi.json` is the source of truth once generated; this file explains the intent behind it.

## Upstream strategy (summary; see ADR-0002)
- We fetch **all** public repos of the org once (`GET /orgs/{org}/repos?type=public&per_page=100`, following `Link: rel="next"`). We build an immutable **snapshot**, cache it, and do all filtering, sorting and pagination locally.
- There's one upstream dataset per org. `type` (all/sources/forks) is a **local** filter on the `fork` flag, so it never multiplies upstream calls. Always using `type=public` also means that a reviewer's token which can see private repos never leaks them.

## Request

| Param | Type | Default | Notes |
|---|---|---|---|
| `org` (path) | string | – | GitHub login, validated `^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$`. Lower-cased for the cache key. |
| `language` | string | unset | Case-insensitive exact match on the primary language. The reserved value `none` matches repos whose language is null. |
| `min_stars` | int ≥ 0 | unset | Inclusive. |
| `archived` | bool | unset | Unset means both. |
| `type` | `all` \| `sources` \| `forks` | `all` | Local filter on `fork`. |
| `sort` | `stars` \| `updated` \| `pushed` \| `name` | `stars` | `updated` = GitHub `updated_at` (literal "last updated"). `pushed` = last code push, a better "activity" signal (bonus). |
| `order` | `asc` \| `desc` | `desc` for stars/updated/pushed; `asc` for name | |
| `limit` | int 1–100 | 30 | |
| `cursor` | opaque string | unset | From `page.next_cursor` / `page.prev_cursor`. |
| `offset` | int ≥ 0 | unset | *Stretch (tel-offset).* Mutually exclusive with `cursor` (400 if both). |

## Ordering semantics (see ADR-0005)
- Primary key per `sort`, then the tiebreaker **`id` ascending** (always ascending, so the order is total and stable).
- `name` compares `casefold()`ed.
- **Nulls sort last regardless of direction.** (Only `pushed_at` can realistically be null today. The rule is general, so adding a nullable sort key later needs no new decision.)
- Empty strings from GitHub (`description: ""`, `language: ""`) are normalised to `null` at ingestion. `license` is `null` when absent, and `license.spdx_id` becomes `null` when GitHub returns `"NOASSERTION"`.

## Cursor (see ADR-0004)
Opaque `base64url(JSON)`:
```json
{"v":1, "q":"<hash of normalised filters+sort+order>", "s":"<snapshot id>", "k":[<sort value>, <id>], "d":"next"|"prev"}
```
- **Keyset**: the next page holds the items strictly after `k` in the query's ordering. A prev page holds the items strictly before `k`, returned in forward order.
- `q` mismatch (a cursor reused with different filters or sort) → **400** `invalid-cursor`. A malformed cursor → 400.
- `s` mismatch (the snapshot was refreshed since the cursor was issued): we still continue by keyset, which is well-defined. The response sets `snapshot.cursor_from_older_snapshot: true` so the UI can say "data refreshed". Rows whose sort key changed between snapshots may move. This is documented, not hidden.

## Response 200 (`application/json`)
```jsonc
{
  "org": "google",
  "items": [{
    "id": 1, "name": "guava", "full_name": "google/guava", "html_url": "https://github.com/google/guava",
    "description": "string|null", "language": "string|null",
    "stars": 0, "forks": 0, "open_issues": 0,
    "archived": false, "fork": false,
    "license": {"spdx_id": "Apache-2.0|null", "name": "string"} | null,
    "topics": ["..."],
    "created_at": "RFC3339", "updated_at": "RFC3339", "pushed_at": "RFC3339|null"
  }],
  "page": {
    "limit": 30, "total": 812,             // total = count after filters
    "has_next": true, "has_prev": false,
    "next_cursor": "string|null", "prev_cursor": "string|null"
  },
  "snapshot": {
    "id": "string", "fetched_at": "RFC3339", "repo_count": 2731,   // count before filters
    "stale": false,                        // true if served past TTL because upstream failed or is revalidating
    "cursor_from_older_snapshot": false
  },
  "rate_limit": {                          // last observed GitHub state; null fields if unknown
    "authenticated": false, "limit": 60, "remaining": 31, "reset_at": "RFC3339"
  }
}
```
Headers: `ETag` (weak, derived from snapshot id + normalised query), `Cache-Control: private, max-age=60`, `X-Request-ID`. A matching `If-None-Match` → 304.

## Errors: `application/problem+json` (RFC 9457, see ADR-0006)
`{type, title, status, detail, instance, request_id, ...extensions}`. `type` is `https://telescope.local/problems/<slug>`.

| Situation | Status | slug | Extras |
|---|---|---|---|
| Bad query param | 422 | `validation-error` | `errors: [{loc,msg}]` |
| Bad/mismatched cursor, cursor+offset | 400 | `invalid-cursor` / `invalid-pagination` | |
| Org not found | 404 | `org-not-found` | `org` |
| GitHub rate limit (primary or secondary), no stale data | 503 + `Retry-After` | `upstream-rate-limited` | `retry_after`, `rate_limit` |
| Budget guard: not enough remaining quota to fetch all pages | 503 + `Retry-After` | `upstream-rate-limited` | `pages_needed` |
| GitHub 5xx / network after retries, no stale data | 502 | `upstream-unavailable` | |
| GitHub timeout after retries, no stale data | 504 | `upstream-timeout` | |

If a stale snapshot exists, any upstream failure is served as **200 with `snapshot.stale: true`** instead.
