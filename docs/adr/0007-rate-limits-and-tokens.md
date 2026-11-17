# ADR-0007: Rate limits with and without a token

- Status: Accepted
- Date: 2026-11-17

## Context
GitHub's REST primary limit is 60 requests/hour unauthenticated and 5,000/hour with a token ([docs](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)). A full fetch of `google` is about 30 pages (research: `rel="last"` page=30). Tokenless, that is half the hourly budget per refresh, so **about two full fetches per hour**, and a third would fail midway. Secondary limits (concurrency, bursts) are separate and cannot be queried ([docs](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api#about-secondary-rate-limits)). The evaluator may or may not supply a token (decisions log #2: fixtures first, a PAT for the final live check).

## Options considered
- **Require a token**: removes the problem, but the app would not run out of the box. Rejected.
- **Fetch and hope**: a rate limit hits mid-walk, wasting the quota already spent and leaving nothing cached.
- **Pre-flight budget guard**: after page 1 we know N (from `Link`) and `x-ratelimit-remaining`, so we can refuse before spending more. Chosen.
- **Quota accounting by ourselves**: duplicates what the headers already tell us.

## Decision
- Token optional (`GITHUB_TOKEN`, ADR-0008). Without it, requests are unauthenticated and `rate_limit.authenticated=false`.
- **Budget guard**: after page 1, if `remaining` is known and `remaining < N - 1`, raise `UpstreamRateLimited(pages_needed=N, retry_after=<seconds to reset>)` *before* fetching pages 2..N. Page 1 is the only wasted call.
- **State tracking**: update from `x-ratelimit-limit/remaining/reset` on **every** response, including 304 and errors (reset is epoch seconds, converted to UTC). It is exposed as metrics (`telescope_github_ratelimit_remaining/limit`, ADR-0009) and in every success response as `rate_limit {authenticated, limit, remaining, reset_at}`, so the UI footer can show "remaining/limit".
- **Primary limit**: 403/429 with `x-ratelimit-remaining: 0` -> `UpstreamRateLimited(retry_after = reset - now)`.
- **Secondary limit**: 403/429 with `retry-after`, or a body containing "secondary rate limit" -> `UpstreamRateLimited(secondary=True, retry_after = retry-after or 60)`. We never retry through it, since the docs warn that continued requests can get an integration banned.
- Mapped to 503 + `Retry-After` (ADR-0006), unless a stale snapshot can be served (ADR-0003).
- Quota-saving measures, in order of impact: the 10 minute TTL, single-flight, then ETag revalidation. The last helps only with a token, because **unauthenticated 304s still count** (research section 4).
- Page concurrency is capped at 8 (ADR-0002; raised from 4 after measurement) to stay clear of secondary limits.

## Consequences
- Pro: we fail fast and cheaply with an actionable `Retry-After` and `pages_needed` rather than burning quota on a doomed walk.
- Pro: the UI can explain the limit, show its reset time and suggest adding a token.
- Con: tokenless use is fragile for big orgs: about two cold fetches per hour, so a second large org will probably hit the guard. Cached/stale data hides this for orgs already fetched. This is stated in the README and the UI message.
- Con: the guard uses the last-known `remaining`, which can be stale when several processes share one IP. A mid-walk limit is still handled (it fails the fetch with no partial cache).
- Con: the guard costs one request when it trips. That is unavoidable, since `N` is only learned from page 1.
