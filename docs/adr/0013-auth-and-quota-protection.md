# ADR-0013: Authentication, per-user rate limiting and GitHub-quota protection

- Status: Accepted (human, 2026-11-21 09:36Z: "yes for the jwts", org allowlist off by default)
- Date: 2026-11-21

## Context
The scarce resource is **GitHub quota**, not our CPU. A cached request costs 0 upstream calls and about 30 ms. Upstream calls are spent only by:
- a cold org: N pages, up to 85 for microsoft;
- a non-existent org: 1 call (the 60 s negative cache only helps with repeats);
- a preview: 1 call (ADR-0012).

One client looping over random org names could drain the 60/h tokenless quota in about a minute, or the 5,000/h token quota in about an hour, and starve everyone else. A request-count limit alone doesn't prevent this, so the limit must be on **upstream spend**.

The deployment is assumed to be internal, behind Tailscale, an identity-aware proxy or similar. Defence in depth still applies: the app needs a per-user identity in order to rate-limit per user.

## Options considered
- **Identity**:
  - **Client IP only**: zero setup, but NAT and proxies merge users, and it is spoofable through `X-Forwarded-For`.
  - **App-managed login**: duplicates the gateway.
  - **Trust the gateway's identity (chosen)**: in production, verify the gateway's JWT against its JWKS, or read Tailscale identity headers from trusted proxy IPs only. In dev, the app mints its own short-lived JWT, so dev exercises the same verification path and the same limiter.
- **CSRF tokens vs bearer tokens**: CSRF protection matters only for ambient credentials (cookies) on state-changing requests. Our API is read-only, and a bearer token in `Authorization` is never sent automatically, so CSRF is impossible by construction. The real cross-site risk is *quota burning*: a malicious page can make a victim's browser fire simple GETs. Requiring `Authorization` (which forces a CORS preflight we never allow) and rejecting `Sec-Fetch-Site: cross-site` closes it. If we ever moved to cookie sessions: `SameSite=Strict` plus a CSRF token.
- **Limiter placement**:
  - **nginx `limit_req` only**: coarse, and blind to cache hits vs. upstream spend.
  - **In-app limiter (chosen)**: knows the cost of each request. nginx can be added later as an outer layer.

## Decision
**Authentication (`AUTH_MODE`)**
- `dev`: the default for local runs. `POST /api/dev/token` (enabled only in this mode) mints an HS256 JWT with `iss=telescope-dev`, `aud=telescope`, `exp` of 1 h, and `sub` taken from the body or defaulting to `dev-user`. The secret comes from `AUTH_DEV_SECRET`, or is random per process if unset. The SPA keeps the token in memory, sends `Authorization: Bearer`, and re-mints once on 401.
- `jwt`: production behind oauth2-proxy, Cloudflare Access or similar. The gateway's JWT is verified against `AUTH_JWKS_URL` with `AUTH_JWT_ISSUER` and `AUTH_JWT_AUDIENCE`, accepting asymmetric algorithms only. The SPA sends nothing; the gateway injects the header.
- `tailscale`: `Tailscale-User-Login` is the identity, trusted **only** when the peer IP is in `AUTH_TRUSTED_PROXIES`.
- `none`: anonymous, keyed by client IP. `X-Forwarded-For` is honoured only from trusted proxies. Used by tests and for opting out explicitly.
- Every mode yields a `Principal(sub, source)`. Missing or invalid credentials return **401** `unauthorized` problem+json with `WWW-Authenticate: Bearer`. `/healthz` and the OpenAPI docs stay public.
- **Cross-site guard**: `Sec-Fetch-Site: cross-site` on `/api/*` returns **403** `cross-site-request`. The app sends no CORS headers in compose, since everything is same-origin through nginx; `CORS_ORIGINS` stays dev-only.

**Rate limiting (token buckets; in memory, or in Redis via Lua when `CACHE_BACKEND=redis` so limits hold across replicas)**
1. **Request rate per principal**: `USER_RATE_PER_MIN=120`, burst 30. Exceeding it returns **429** `client-rate-limited` with `Retry-After`. This is deliberately not our 503, which means GitHub limited *us*.
2. **Upstream spend per principal**: `USER_UPSTREAM_BUDGET=100` calls per `USER_UPSTREAM_WINDOW_S=600`. Calls are charged to the principal who *initiates* them. Cold walks are charged page 1 first, then the remaining `pages_total - 1` atomically before fanning out, so a walk the user can't afford is refused before it burns anything. 404 lookups and previews are charged too. Joining someone else's in-flight walk, and cache hits, cost 0. Exceeding the budget returns **429** `upstream-budget-exceeded` with `Retry-After`.
3. **Global reserve**: user-initiated spend may not take GitHub's `remaining` below `UPSTREAM_RESERVE_FRACTION=0.2` × `limit`. The reserve is kept for background SWR refreshes, which run as the `system` principal and are never charged to users. A refusal returns 503 `upstream-rate-limited` (existing type) with `Retry-After`, the reset time.
4. **Cold-walk concurrency**: at most `MAX_CONCURRENT_WALKS=2` org walks at once globally; the rest wait.
5. **Org allowlist**: `ORG_ALLOWLIST` (comma list) is **off (empty) by default**. When set, other orgs get **403** `org-not-allowed` before any cache or upstream work.

**Hardening**
- nginx sets a CSP (`default-src 'self'`; `style-src 'self' 'unsafe-inline'` for Mermaid), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `frame-ancestors 'none'`. The inline theme script moves to a file so `script-src 'self'` holds.
- Logs carry `principal` on every request and every rate-limit rejection. Metrics `telescope.client_rejections{reason}` and `telescope.upstream_spend{initiator=user|system}` use no per-user labels, to avoid cardinality blow-up; per-user breakdowns come from Loki.

## Consequences
- A single user can't exhaust the shared quota: at most 100 calls per 10 min, and never the last 20 %.
- Local evaluation needs no setup, because `dev` mode mints tokens transparently.
- Tests default to `AUTH_MODE=none`, plus dedicated auth and limiter suites.
- A dev token is not a security boundary. Anyone who can reach the API can mint one, so production must run `jwt` or `tailscale`. The README says so.
- New 401/403/429 problem types are added to the contract, the OpenAPI spec and the generated client.
