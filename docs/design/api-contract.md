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
| `offset` | int 0..100000 | unset | Offset mode. Mutually exclusive with `cursor` (400 `invalid-pagination` if both). Cursors are null in this mode. |

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
    "created_at": "RFC3339|null", "updated_at": "RFC3339|null", "pushed_at": "RFC3339|null"
  }],
  "page": {
    "limit": 30, "total": 812,             // total = count after filters
    "has_next": true, "has_prev": false,
    "next_cursor": "string|null", "prev_cursor": "string|null",
    "offset": "int|null (set in offset mode, null in cursor mode)"
  },
  "snapshot": {
    "id": "string", "fetched_at": "RFC3339", "repo_count": 2731,   // count before filters
    "stale": false,                        // true only when served past TTL+SWR because upstream failed (within the 60s SWR window, cached data is served as fresh while a background refresh runs)
    "cursor_from_older_snapshot": false
  },
  "rate_limit": {                          // last observed GitHub state; null fields if unknown
    "authenticated": false, "limit": 60, "remaining": 31, "reset_at": "RFC3339"
  }
}
```
Headers: `ETag` (weak, derived from snapshot id + normalised query), `Cache-Control: private, max-age=60`, `X-Request-ID`. A matching `If-None-Match` → 304.

### Provisional responses during a cold load (ADR-0012)
On a cold miss for a first-page query (no `cursor`, `offset` absent or 0), the endpoint waits up to `COLD_WAIT_MS` (default 1500) for the walk. If it lands, the response is as above. Otherwise it answers `200` with a provisional page and the client re-requests the same URL until `snapshot.complete` is `true`. Additive fields:

- `snapshot.complete: bool` (default `true`). `false` means the cold load is still running.
- `snapshot.progress: {pages_done, pages_total | null} | null`, non-null only when `complete` is false (`pages_total` is null until page 1 lands).
- `snapshot.id`, `snapshot.fetched_at`, `snapshot.repo_count` are `null` only when `complete` is false.
- `page.total` is `null` while loading, unless the preview came from Search (its `total_count`).
- `page.provisional_reason`: `preview-disabled | preview-skipped | preview-inexact | preview-unavailable | null`. Non-null only when `complete` is false and `items` is empty. With `complete: false` and non-empty `items`, the items are an exact provisional first page. An exact preview with zero matches has empty `items` and a null reason.
- While `complete` is false: `has_next`/`has_prev` are `false`, both cursors are `null`; headers are `Cache-Control: no-store` and `Retry-After: 1`, with no `ETag`.

Previews: `sort=name` asc reuses the walk's own page 1 (0 extra calls); `name` desc/`updated`/`pushed` use one `GET /orgs/{org}/repos` call (`sort=full_name|updated|pushed`, `per_page=100`); `stars` uses one `GET /search/repositories` call with the filters as qualifiers. A preview is exact when the local filters leave at least `limit` matches or upstream returned fewer than 100 items (and, for asc `updated`/`pushed`, no item has a null sort key); otherwise `items` is empty with `preview-inexact`. `PREVIEW_MODE=first` (default) allows one upstream preview per cold load per org (the query that started the load; later queries get `preview-skipped`), `per-query` one per distinct normalised query, `off` none. Previews are charged to the initiating principal (ADR-0013), cached for the life of the load, and any failure degrades to `preview-unavailable`; it never fails the request or the walk. Cursor, `offset > 0` and stale/SWR requests block exactly as before.

## Authentication (ADR-0013)
Every `/api/*` request resolves to a principal; `/healthz`, `/docs` and `/openapi.json` are public.

| `AUTH_MODE` | Credential | Principal |
|---|---|---|
| `dev` (default) | `Authorization: Bearer <HS256 JWT>` minted by `POST /api/dev/token` (`iss=telescope-dev`, `aud=telescope`, 1 h) | `sub` |
| `jwt` | `Authorization: Bearer <JWT>` from the gateway, verified against `AUTH_JWKS_URL` (asymmetric algorithms only; `iss`/`aud`/`exp` checked) | `sub` |
| `tailscale` | `Tailscale-User-Login`, honoured only from `AUTH_TRUSTED_PROXIES` | login |
| `none` | none | client IP (`X-Forwarded-For` honoured only from trusted proxies) |

`POST /api/dev/token` (optional body `{"sub": "<1-64 chars>"}`, default `dev-user`) returns `{access_token, token_type: "Bearer", expires_in}`. It answers `404` in every mode but `dev`. A dev token is not a security boundary.

Per-principal limits: `USER_RATE_PER_MIN` (burst `USER_RATE_BURST`) on requests, `USER_UPSTREAM_BUDGET` GitHub calls per `USER_UPSTREAM_WINDOW_S`, and a global reserve (`UPSTREAM_RESERVE_FRACTION` of GitHub's limit) that only background refreshes may spend. Cache hits and joining another caller's in-flight walk cost nothing.

## Errors: `application/problem+json` (RFC 9457, see ADR-0006)
`{type, title, status, detail, instance, request_id, ...extensions}`. `type` is `https://telescope.local/problems/<slug>`.

| Situation | Status | slug | Extras |
|---|---|---|---|
| Bad query param | 422 | `validation-error` | `errors: [{loc,msg}]` |
| Bad/mismatched cursor, cursor+offset | 400 | `invalid-cursor` / `invalid-pagination` | |
| Org not found | 404 | `org-not-found` | `org` |
| GitHub rate limit (primary or secondary), no stale data | 503 + `Retry-After` | `upstream-rate-limited` | `retry_after`, `rate_limit` |
| Budget guard: not enough remaining quota to fetch all pages | 503 + `Retry-After` | `upstream-rate-limited` | `pages_needed` |
| No/invalid credentials (`AUTH_MODE` dev/jwt/tailscale) | 401 + `WWW-Authenticate: Bearer` | `unauthorized` | |
| `Sec-Fetch-Site: cross-site` on `/api/*` | 403 | `cross-site-request` | |
| Org not on `ORG_ALLOWLIST` (when set) | 403 | `org-not-allowed` | |
| Per-client request rate exceeded | 429 + `Retry-After` | `client-rate-limited` | `retry_after` |
| Per-client upstream-call budget exceeded (incl. a cold walk it cannot afford) | 429 + `Retry-After` | `upstream-budget-exceeded` | `retry_after`, `pages_needed` |
| User spend would dip into the global reserve | 503 + `Retry-After` | `upstream-rate-limited` | `retry_after`, `rate_limit`, `pages_needed` |
| GitHub 5xx / network after retries, no stale data | 502 | `upstream-unavailable` | |
| GitHub timeout after retries, no stale data | 504 | `upstream-timeout` | |

If a stale snapshot exists, any upstream failure is served as **200 with `snapshot.stale: true`** instead.
