# ADR-0006: Error handling

- Status: Accepted
- Date: 2026-11-17

## Context
Errors come from three places: client input, GitHub (404, rate limits, 5xx, timeouts, network), and our own bugs. The UI needs distinct, machine-readable states (not found, rate limited, retry later). A reviewer-friendly API should use a standard error format and never turn a transient upstream problem into wrong data.

## Options considered
**Error format**: ad-hoc `{"error": "..."}` (no standard, no content type), FastAPI's default `{"detail": ...}` (inconsistent shapes between 422 and others), or **RFC 9457 `application/problem+json`** ([RFC](https://www.rfc-editor.org/rfc/rfc9457.html)). The last is chosen: a standard, extensible, with `type` a stable slug the frontend can switch on.

**Upstream rate-limit status**: pass GitHub's 403/429 through, return 429, or return 503 (see below).

**Retries**: none (simple but brittle), retry everything (hammers GitHub and burns quota), or retry only transient failures with backoff and jitter. The last is chosen.

## Decision
Body: `{type, title, status, detail, instance, request_id, ...extensions}`, with `type = https://telescope.local/problems/<slug>`, driven by the `slug/status/title` on each exception in `errors.py`.

| Situation | Status | slug | Extras |
|---|---|---|---|
| Bad query param | 422 | `validation-error` | `errors: [{loc,msg}]` |
| Bad/mismatched cursor | 400 | `invalid-cursor` | |
| cursor + offset (stretch) | 400 | `invalid-pagination` | |
| Org not found (GitHub 404) | 404 | `org-not-found` | `org` |
| Primary or secondary rate limit, no stale data | 503 + `Retry-After` | `upstream-rate-limited` | `retry_after`, `rate_limit` |
| Budget guard (ADR-0007) | 503 + `Retry-After` | `upstream-rate-limited` | `pages_needed` |
| GitHub 5xx/network after retries, no stale data | 502 | `upstream-unavailable` | |
| GitHub timeout after retries, no stale data | 504 | `upstream-timeout` | |
| Any other GitHub 403 | 502 | `upstream-unavailable` | |

**Why 503, not 429, for upstream limits.** 429 means "*you* are sending too many requests". Our client is not; our server's shared upstream quota is exhausted. 503 + `Retry-After` says "temporarily unable to serve, retry later", and it keeps 429 free for limiting our own callers should that be added. (Forwarding GitHub's 403 would be wrong too: 403 means the caller is forbidden.)

**Retries**: only 5xx, `httpx.TimeoutException` and `httpx.TransportError`; up to 3, exponential backoff with **full jitter** (`uniform(0, min(8s, 0.5s * 2^attempt))`) per the [AWS analysis](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/). Never 4xx. The delay goes through an injected `sleep` for tests. A rate limit is not retried in-request: `retry-after` is honoured by reporting it to the caller.

**No partial caching**: a failure on any page fails the whole fetch, and siblings are cancelled. A `Snapshot` exists only for a complete walk.

**Serve stale**: if a cached snapshot exists (age < 24h), any `UpstreamError` becomes a **200 with `snapshot.stale=true`** (ADR-0003). Problem responses only occur when there is nothing to serve. `OrgNotFound` is never masked by stale data.

Every problem carries `request_id` (also in `X-Request-ID`, ADR-0009), and the problem content type is advertised in `openapi.json` (ADR-0010).

## Consequences
- Pro: the frontend branches on `type` and `status`, never on message text. Errors are uniform, including validation.
- Pro: the user sees degraded-but-working data in most upstream failures.
- Con: 503 for upstream limits departs from the "obvious" 429. The reason is documented here and in the contract.
- Con: a client that treats 502/503/504 differently has to read `type`. That is what the slug is for.
- Con: jittered backoff makes tests non-deterministic unless the rng and sleep are injected, which we do (ADR-0011).
