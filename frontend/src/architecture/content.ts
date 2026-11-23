import diagram1 from './diagrams/01-context.mmd?raw'
import diagram2 from './diagrams/02-classes.mmd?raw'
import diagram3 from './diagrams/03-sequence-cold.mmd?raw'
import diagram4 from './diagrams/04-sequence-progressive.mmd?raw'
import diagram5 from './diagrams/05-sequence-refresh.mmd?raw'
import diagram6 from './diagrams/06-cache-states.mmd?raw'
import diagram7 from './diagrams/07-error-mapping.mmd?raw'
import diagram8 from './diagrams/08-deployment-now.mmd?raw'
import diagram9 from './diagrams/09-deployment-prod.mmd?raw'

export type DiagramKind =
  'Component' | 'Class' | 'Sequence' | 'State' | 'Flow' | 'Deployment'

export interface DiagramEntry {
  id: string
  title: string
  kind: DiagramKind
  summary: string
  source: string
}

export interface Decision {
  adr: string
  title: string
  decision: string
  why: string
  alternatives: string[]
  tradeoffs: string[]
  revisitWhen: string
}

export interface RoadmapArea {
  area: string
  now: string
  next: string[]
  why: string
}

export interface Overview {
  title: string
  paragraphs: string[]
  principles: string[]
}

export const diagrams: DiagramEntry[] = [
  {
    id: 'context',
    title: 'System context and components',
    kind: 'Component',
    summary:
      'The browser talks only to nginx. nginx serves the SPA and proxies /api/ to the FastAPI app. Every API request passes the cross-site guard, the Authenticator (a dev-minted JWT locally, the gateway JWT or Tailscale identity in production) and the RateLimiter before the route. The route reads the SnapshotService, or the PreviewService for a provisional first page, and every upstream call passes the UpstreamGovernor before the GitHub client, which talks to the REST API and, for stars previews, the Search API. Telemetry leaves over OTLP/HTTP to the otel-lgtm container; Redis is an optional shared store for snapshots and limiter buckets.',
    source: diagram1,
  },
  {
    id: 'classes',
    title: 'Domain model and classes',
    kind: 'Class',
    summary:
      'The contract types from models.py (now including SnapshotInfo.complete and progress and PageInfo.provisional_reason), the cache and store types with Flight and LoadProgress, the PreviewService, the auth and rate-limit types (Principal, Authenticator, RateLimiter with in-memory and Redis implementations, UpstreamGovernor), the GitHub client, the query result and cursor, and the error hierarchy that problems.py maps to RFC 9457 responses.',
    source: diagram2,
  },
  {
    id: 'sequence-cold',
    title: 'Cold request: the walk',
    kind: 'Sequence',
    summary:
      'What the walk does inside the flight: page 1, the page count from Link rel=last, the budget guard and the governor charge for the remaining pages, then at most 8 pages in flight. Concurrent identical requests share the one in-flight task. If it finishes within COLD_WAIT_MS the response is complete; otherwise see the progressive diagram.',
    source: diagram3,
  },
  {
    id: 'sequence-progressive',
    title: 'Progressive cold load',
    kind: 'Sequence',
    summary:
      'Request, authentication and buckets, then a cold miss starts the walk charged to the initiator. After COLD_WAIT_MS the route answers 200 with a provisional page from one lazy preview call and a progress count (no-store, Retry-After 1). The client polls the same URL, which joins the flight at no upstream cost, until the snapshot lands and the response is complete.',
    source: diagram4,
  },
  {
    id: 'sequence-refresh',
    title: 'Refresh, revalidation and stale serving',
    kind: 'Sequence',
    summary:
      'Inside the SWR window the cached snapshot is returned at once and refreshed in the background. After it, the client revalidates each page with If-None-Match; all 304s keep the same snapshot id. On upstream error a copy under 24h old is served as stale.',
    source: diagram5,
  },
  {
    id: 'cache-states',
    title: 'Cache entry lifecycle',
    kind: 'State',
    summary:
      'Absent, Fetching, Fresh (under 600s), the SWR window (to 660s), Expired, Revalidating, Stale served (under 24h) and the error state beyond max-stale, plus the 60s negative cache for unknown orgs.',
    source: diagram6,
  },
  {
    id: 'error-mapping',
    title: 'Request guards and error classification',
    kind: 'Flow',
    summary:
      'The guard chain first: 403 cross-site-request, 401 unauthorized, 429 client-rate-limited, 403 org-not-allowed, then the governor (the 503 reserve refusal, 429 upstream-budget-exceeded, or a 200 stale when the user is over budget and an expired snapshot exists). Then how github/client.py classifies each GitHub response into a domain error, how retries use full jitter, and how problems.py and the stale rule turn that into a status code.',
    source: diagram7,
  },
  {
    id: 'deployment-now',
    title: 'Deployment today (Docker Compose)',
    kind: 'Deployment',
    summary:
      'Four services: web on 8080, api on 8000, lgtm (Grafana 3000, OTLP 4317 and 4318) and an optional redis profile. GITHUB_TOKEN flows from .env into the api container only. AUTH_MODE=dev mints a 1h JWT at /api/dev/token; limiter buckets are in memory unless the redis profile is on.',
    source: diagram8,
  },
  {
    id: 'deployment-prod',
    title: 'Target production deployment',
    kind: 'Deployment',
    summary:
      'A gateway (oauth2-proxy or Tailscale) in front of a CDN and ALB issues the identity the api verifies (JWKS or trusted proxy headers). At least two autoscaled api replicas, ElastiCache Redis for shared snapshots, a distributed lock and the limiter and budget buckets, a refresher worker with a scheduler, GitHub App tokens from Secrets Manager, webhook invalidation, and an OTel gateway to Grafana Cloud.',
    source: diagram9,
  },
]

export const decisions: Decision[] = [
  {
    adr: '0001',
    title: 'Monorepo, layered backend, Makefile plus mise',
    decision:
      'One repo with backend, frontend, infra and docs. The backend is layered client, cache service, pure query engine, route, each depending only downwards on small interfaces (Fetcher, SnapshotStore). models.py and errors.py are dependency-free. A Makefile holds the real targets and mise pins tool versions and aliases them.',
    why: 'A timeboxed take-home run locally needs one clone, one command per task and atomic contract changes. Dependency-free models let the client, cache and query engine be tested in isolation.',
    alternatives: [
      'Polyrepo: ceremony for one API and one UI.',
      'Flask or Django: sync by default and no generated contract.',
      'Next.js: SSR adds a server runtime nobody needs.',
      'mise only or Make only: Make does not pin versions, mise tasks are less portable.',
    ],
    tradeoffs: [
      'No CI, so nothing blocks a bad push; checks are make targets the reviewer runs.',
      'Make is awkward on Windows.',
      'Two lockfiles (uv.lock, pnpm-lock.yaml) to keep committed.',
    ],
    revisitWhen:
      'A second team or a deploy target appears: add a CI workflow that calls the same make targets.',
  },
  {
    adr: '0002',
    title: 'Fetch all pages, then filter locally',
    decision:
      'Walk GET /orgs/{org}/repos?type=public&sort=full_name&direction=asc&per_page=100 once per org: page 1, read rel=last, then pages 2..N with a semaphore of 8 under a TaskGroup. All filtering, sorting and pagination happen on the in-memory snapshot. The API type parameter is a local filter on the fork flag.',
    why: 'GitHub cannot filter by language or stars or sort by stars. Search is capped at 1,000 results, allows 10 requests a minute tokenless and has no language:none. GraphQL needs a token. Fetching all once costs about 30 calls for google and then zero per client request. sort=full_name keeps page boundaries stable, which makes per-page ETags useful.',
    alternatives: [
      'Pass-through to GitHub: no language, stars or star sorting.',
      'Search API: 1,000-result cap and 10 requests a minute.',
      'GraphQL: requires a token, excludes tokenless use.',
      'Serial page walk: safest, but about 30 round trips.',
    ],
    tradeoffs: [
      'Cold requests are slow: measured 1 to 1.5s per page, so google took 13s tokenless at concurrency 4 and 7.3s with a token at concurrency 8, and microsoft (85 pages) took 33s at 4.',
      "Concurrency deliberately deviates from GitHub's serial-requests advice; the default was raised from 4 to 8 after measuring and is a setting (1 restores serial).",
      'Memory is O(repos per org) per cached org.',
      'Data can be a TTL old.',
    ],
    revisitWhen:
      'Orgs get so large that the cold walk or the memory is unacceptable: move to a background refresher with a 202 and progress, or to Postgres.',
  },
  {
    adr: '0003',
    title: 'Snapshot cache with SWR, single-flight and stale-on-error',
    decision:
      'SnapshotService over a SnapshotStore Protocol. Under 600s is a hit. From 600s to 660s it returns the cached snapshot and refreshes once in the background. Beyond that it revalidates synchronously with per-page If-None-Match; all 304s keep the same snapshot id with a new fetched_at. Any UpstreamError serves the cached copy with stale=true while it is under 24h old. One shared task per org coalesces concurrent misses. An unknown org is negative-cached for 60s. Our responses carry a weak ETag and Cache-Control private, max-age=60 (no-cache when stale).',
    why: 'One cold fetch costs about 30 requests against a 60 an hour tokenless budget, so steady state must cost nothing and an outage must not become an error page. Warm requests measured about 30ms.',
    alternatives: [
      'Redis only: extra infrastructure for a local demo.',
      'No SWR: users would wait on every refresh.',
      'Fail on upstream error: turns a rate limit into an outage.',
      'No single-flight: N concurrent misses become N walks.',
    ],
    tradeoffs: [
      'Unauthenticated 304s still count against the limit (observed x-ratelimit-used 10 to 11), so ETag revalidation saves quota only with a token.',
      'Single-flight and the negative cache live in process memory, so each replica coalesces separately.',
      'The SWR window returns stale=false for data up to 60s past TTL.',
      'While upstream is down, every request past the SWR window retries GitHub, because nothing records the failure.',
    ],
    revisitWhen:
      'More than one replica runs: move the lock and negative cache to Redis and add a circuit breaker.',
  },
  {
    adr: '0004',
    title: 'Keyset cursors by default, offset as an alternative',
    decision:
      'Cursor is base64url JSON carrying a version, a query hash, the snapshot id, the (sort value, id) key and a direction. Position is found by bisect over sort-key tuples, so it works even if the key row is gone. The query hash excludes limit, cursor and offset, so page size can change mid-walk. A snapshot id mismatch still continues and sets cursor_from_older_snapshot. offset (0 to 100,000) is mutually exclusive with cursor (400 invalid-pagination) and returns null cursors.',
    why: 'A keyset position is stable under inserts and deletes before it and costs O(log n). The snapshot id is a content hash, so a revalidation that changed nothing keeps cursors current. Failing every in-flight user at each refresh would be worse than a flagged imperfection.',
    alternatives: [
      'Offset only: rows are skipped or repeated when data shifts.',
      'page and per_page: offset with other arithmetic, cut for time.',
      'Reject cursors from older snapshots: breaks users at every refresh.',
    ],
    tradeoffs: [
      'No jump-to-page for cursor mode; offset mode exists for that and may duplicate or skip rows across a refresh.',
      'Cursors are not signed; tampering only affects the tamperer.',
      'A changed sort key (stars) can move a row across snapshots, which is flagged rather than hidden.',
    ],
    revisitWhen:
      'Clients need stable deep links to a position across refreshes: persist snapshots (Postgres) and pin cursors to a snapshot.',
  },
  {
    adr: '0005',
    title: 'Null and missing-data semantics',
    decision:
      'Normalise at ingestion: empty strings become null, NOASSERTION licence ids become null, topics default to []. Sorting uses a tuple key (is_null, directed value, id) so nulls sort last in both directions and id ascending is the tiebreaker. language=none matches repos with no language, and language matching is case-insensitive. Names compare with casefold().',
    why: 'Keyset pagination needs a total, deterministic order. One spelling of no value keeps every layer and the UI simpler, and nulls first would put unknown dates at the top of a newest-first list.',
    alternatives: [
      'Pass GitHub values through: two spellings of nothing.',
      'SQL-style nulls that flip with direction.',
      'Search-style language:none: does not exist upstream.',
    ],
    tradeoffs: [
      'A language literally named None would be unreachable by name.',
      'Collapsing empty and null loses a distinction GitHub may draw.',
      'The custom comparison is more code than sorted(reverse=True).',
    ],
    revisitWhen:
      'A nullable sort key needs different placement semantics, or GitHub starts distinguishing empty from null.',
  },
  {
    adr: '0006',
    title: 'RFC 9457 problems, 503 for upstream limits, jittered retries',
    decision:
      'Every error is application/problem+json with a type slug, request_id and extensions. Upstream rate limits (primary, secondary, budget guard) are 503 with Retry-After; other GitHub failures are 502, timeouts 504, an unknown org 404, bad cursors 400, validation 422. Only 5xx, timeouts and transport errors are retried, up to 3 times with delay uniform(0, min(8s, 0.5s x 2^attempt)). Rate limits are not retried in-request. A failure on any page fails the whole fetch.',
    why: 'The frontend should branch on type and status, never on message text. 429 means the caller is sending too much; here our shared upstream quota is exhausted, so 503 with Retry-After is the honest signal and 429 stays free for limiting our own callers.',
    alternatives: [
      'Ad-hoc error JSON or FastAPI default detail: inconsistent shapes.',
      "Forward GitHub's 403: means the caller is forbidden.",
      'Return 429 for upstream limits.',
      'Retry everything: hammers GitHub and burns quota.',
    ],
    tradeoffs: [
      '503 departs from the obvious 429; the reason is documented.',
      'Clients that treat 502, 503 and 504 differently must read the slug.',
      'Jitter makes tests random unless rng and sleep are injected, which they are.',
    ],
    revisitWhen:
      'Done in ADR-0013: 429 is now used for our own callers. Revisit if a gateway takes over per-user limiting.',
  },
  {
    adr: '0007',
    title: 'Optional token with a pre-flight budget guard',
    decision:
      'GITHUB_TOKEN is optional. Rate-limit state is updated from every response, including 304s and errors, keeping the lowest remaining within one reset window because concurrent pages finish out of order. After page 1, if remaining is known and below N minus 1, the client raises UpstreamRateLimited with pages_needed and Retry-After before fetching pages 2..N. A primary limit is 403 or 429 with remaining 0; a secondary limit is retry-after or the body text, never retried.',
    why: 'Tokenless is 60 requests an hour and google needs about 30, so about two cold fetches an hour. Failing fast with an actionable Retry-After beats burning quota on a walk that cannot finish. In the end-to-end run, microsoft with 17 requests left was refused with pages_needed 85 after one request.',
    alternatives: [
      'Require a token: the app would not run out of the box.',
      'Fetch and hope: a mid-walk limit wastes the spent quota and caches nothing.',
      'Own quota accounting: duplicates the headers.',
    ],
    tradeoffs: [
      'Tokenless use is fragile for big orgs; cached or stale data hides it for orgs already fetched.',
      'The guard trusts the last known remaining, which can be stale when processes share an IP.',
      'The guard costs one request when it trips.',
      'ADR text still says concurrency is capped at 4; the default is now 8.',
    ],
    revisitWhen:
      'Several tokens or a GitHub App are available: replace the single remaining counter with a per-token budget scheduler.',
  },
  {
    adr: '0008',
    title: 'Secrets from the environment, redacted everywhere',
    decision:
      'Settings reads GITHUB_TOKEN as a SecretStr, and a blank value means tokenless. The token is used in one place, the Authorization header of the GitHub client. A logging filter redacts the token and Authorization or Bearer text. .env is git-ignored with a committed .env.example. Production injects the variable from a secrets manager. A fine-grained, read-only, public-repositories PAT is the recommended scope.',
    why: 'A leak must be impossible through git, logs, responses or the bundle, and the app must start with no token. We only read public data, so even a leaked token reads nothing the world cannot.',
    alternatives: [
      'Committed config or baked images: leak through history and layers.',
      'Compose secrets files: needs a file-reading path for little gain.',
      'Token supplied by the browser: puts a credential in the frontend.',
    ],
    tradeoffs: [
      'Environment variables are visible to anyone who can inspect the container.',
      'Redaction is pattern based, so an encoded token would slip through; the code avoids logging credentials at all.',
      'No rotation story beyond replacing the variable and restarting.',
    ],
    revisitWhen:
      'The service is deployed for real: GitHub App installation tokens that rotate hourly and a *_FILE style mount.',
  },
  {
    adr: '0009',
    title: 'OpenTelemetry to otel-lgtm, a metrics facade, JSON logs',
    decision:
      'Programmatic OTel setup that is a no-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set, exporting OTLP/HTTP to grafana/otel-lgtm 0.41.0. A metrics facade (cache_lookup, github_request, github_rate_limit, upstream_fetch) keeps OTel out of business code. JSON logs carry request_id, trace_id and span_id, and a request-id middleware echoes X-Request-ID. A provisioned Grafana dashboard covers HTTP, cache, GitHub calls, rate limit, logs and traces.',
    why: 'The reviewer should see cache hits, upstream calls and the quota with one make up, with click-through from logs to traces. The facade makes metrics free in tests.',
    alternatives: [
      'Separate Prometheus, Loki, Tempo and Grafana services: more YAML for no benefit.',
      'The zero-code instrument agent: less explicit and fights uvicorn reload.',
      'structlog: more bridging to stdlib and uvicorn.',
      'Browser OTel: bundle weight and CORS for little gain.',
    ],
    tradeoffs: [
      'Python OTel logs are not stable, so versions are pinned and stdout JSON remains.',
      'Metric names depend on Prometheus translation and the semconv opt-in.',
      'otel-lgtm data is ephemeral.',
      'No frontend telemetry.',
    ],
    revisitWhen:
      'Production: replace otel-lgtm with a Collector gateway to a managed backend and add browser RUM.',
  },
  {
    adr: '0010',
    title: 'FastAPI-generated contract and a generated typed client',
    decision:
      'openapi.json is exported deterministically from the Pydantic models and committed. openapi-typescript generates schema.d.ts and openapi-fetch wraps it. Error responses are post-processed to application/problem+json so errors are typed as Problem. Two drift checks run locally: a pytest compares the export with the committed file, and pnpm gen:api:check compares the generated types.',
    why: 'One source of truth with each hop checked: code to openapi.json to schema.d.ts. A types-only client has the least generated code to review.',
    alternatives: [
      'Hand-written OpenAPI: drifts.',
      'orval: more machinery than one GET needs.',
      'hey-api: pre-1.0.',
    ],
    tradeoffs: [
      'A contract change needs make gen-client and two committed files.',
      'Types are not a runtime validator; responses are trusted.',
      'FastAPI or Pydantic upgrades produce spec diffs.',
      'The problem+json rewrite is a small hack over FastAPI.',
    ],
    revisitWhen:
      'The API has outside consumers: version it under /api/v1 and add Schemathesis in CI.',
  },
  {
    adr: '0011',
    title: 'Fast, offline, parallel-safe tests',
    decision:
      'pytest with -n auto, respx at the transport level with a fixture builder that produces real Link and rate-limit headers, and injected now, sleep and rng so TTL, SWR and backoff are instant and deterministic. The query engine is tested with pure table-driven and seeded property-style walks. The frontend uses Vitest with MSW handlers typed from the same paths type. The suite is 255 backend and 48 frontend tests.',
    why: 'Tests must not depend on the network or on 60 requests an hour, and must not share state because agents work in parallel.',
    alternatives: [
      'The real GitHub API in tests: slow, flaky and burns quota.',
      'Patching httpx: couples tests to internals.',
      'Hypothesis: extra dependency.',
      'Serial runs.',
    ],
    tradeoffs: [
      'respx fixtures encode our belief about GitHub; one manual live check mitigates that.',
      'Injecting clocks adds constructor parameters.',
      'Seeded walks have no shrinking.',
      'No browser end-to-end tests.',
    ],
    revisitWhen: 'CI exists: add Schemathesis and Playwright against compose.',
  },
  {
    adr: '0012',
    title: 'Progressive cold load: a fast provisional first page with progress',
    decision:
      'On a cold miss the snapshot walk runs as a Flight with observable LoadProgress. The route waits COLD_WAIT_MS (1.5s); if the snapshot has not landed it answers 200 with snapshot.complete=false, progress {pages_done, pages_total}, a null snapshot id, null cursors, Cache-Control no-store and Retry-After 1. Items come from one PreviewService call chosen by sort: the list endpoint with sort=full_name, updated or pushed, or the Search API for stars with the filters translated to qualifiers. A list preview is used only when it is provably an exact prefix of our ordering; otherwise items are empty and page.provisional_reason says why (preview-disabled, preview-skipped, preview-inexact, preview-unavailable). The client re-requests the same URL every second until complete; re-requests join the flight and reuse the cached preview, so polling costs no upstream call. The contract change is additive: complete defaults to true and the new fields are nullable.',
    why: 'ADR-0002 stays right for every request after the first; only the blank 7 to 33s wait was wrong. Probing showed one call of about 1s returns exactly our first page for every sort. Results computed from the pages loaded so far would be wrong for any sort but name, so the first page must come from an upstream that sorts for us. First paint dropped to about 2.8s for google by stars (6.5s complete) and 1.5s for a free name preview.',
    alternatives: [
      'Block until complete (before): 7 to 33s of nothing.',
      'Serve results from the pages loaded so far: correct only for name ascending, confidently wrong for stars.',
      'A 202 plus a job resource to poll: a second resource and client state machine, and nothing to look at while waiting.',
      'Server-Sent Events: nice UX but needs proxy_buffering off, multi-replica fan-out and more tests; kept as a drop-in upgrade.',
      'Eager preview, started with the walk: saves about 1s more, but spends a call even when the walk finishes inside the wait. Rejected to minimise quota; opt-in follow-up tel-625.',
    ],
    tradeoffs: [
      'Lazy preview: it starts only after the cold wait expires, so first paint is the wait plus the preview (about 2.7 to 2.8s), not 1.5s.',
      'One preview per cold load per org (PREVIEW_MODE=first, the default): later filter or sort changes during the same load show progress only. A name ascending first query reuses page 1 of the walk and costs 0 extra calls; the worst case is N + 1 calls.',
      'Search previews request per_page=limit, not 100: measured 2.9s for 100 results against about 1s for 30, and safe because Search applies the filters itself.',
      'Search is index-backed and can lag the list endpoint, so the page is labelled provisional and the swap reconciles it. Search has its own quota (10 a minute tokenless); when exhausted the preview degrades to progress only, never to an error.',
      'A filtered list preview is often inexact (microsoft updated plus python has about 21 Python repos in the newest 100, under the 30 needed), so those loads show progress only until tel-1w6.',
      'Progress and previews live in process memory, so each replica reports its own (follow-up tel-aw3).',
    ],
    revisitWhen:
      'Multiple replicas or proxies that tolerate long-lived connections: share progress in Redis and add an SSE transport with the same response shape (tel-aw3).',
  },
  {
    adr: '0013',
    title: 'Authentication, per-user rate limiting and GitHub-quota protection',
    decision:
      "Every API request gets a Principal from an Authenticator selected by AUTH_MODE: dev (the app mints a 1h HS256 JWT at /api/dev/token and the SPA sends it as a bearer), jwt (the gateway's JWT verified against its JWKS, asymmetric algorithms only), tailscale (Tailscale-User-Login, trusted only from AUTH_TRUSTED_PROXIES) or none (anonymous, keyed by client IP, for tests). Missing or invalid credentials are 401 unauthorized. A cross-site guard returns 403 cross-site-request for Sec-Fetch-Site: cross-site. Token buckets then limit two things per principal: the request rate (120 a minute, burst 30, 429 client-rate-limited) and upstream spend (100 calls per 10 minutes, 429 upstream-budget-exceeded). Spend is charged to whoever initiates the call: page 1 first, then the remaining pages atomically before fanning out, so an unaffordable walk is refused before it spends anything; 404 lookups and previews are charged too; cache hits and joining someone else's flight cost 0. User spend may not take GitHub's remaining below a 20% reserve, which background SWR refreshes (the system principal, never charged) can use; a refusal is the existing 503 upstream-rate-limited. At most 2 org walks run at once. ORG_ALLOWLIST is off by default and gives 403 org-not-allowed when set. Buckets are in memory, or Redis Lua scripts when CACHE_BACKEND=redis so limits hold across replicas.",
    why: "The scarce resource is GitHub quota, not CPU. One client looping over random org names could drain 60 an hour tokenless in about a minute, or 5,000 an hour with a token in about an hour, and starve everyone else. A request-count limit cannot see that, so the limit is on upstream spend, per user, which needs an identity. The deployment is internal, so we trust the gateway's identity rather than build a login; dev mode mints tokens so local runs exercise the same verification path and limiter.",
    alternatives: [
      'Client IP only: NAT merges users and X-Forwarded-For is spoofable.',
      'An app-managed login: duplicates the gateway.',
      'nginx limit_req only: coarse, and blind to cache hits against upstream spend. It can be added later as an outer layer.',
      'CSRF tokens: see the trade-offs; not applicable here.',
      'A request-rate limit without a spend limit: does not stop a quota-draining walk.',
    ],
    tradeoffs: [
      'CSRF protection is not applicable: the API is read-only and the bearer token in Authorization is never sent automatically. The real cross-site risk is a hostile page making a victim browser burn quota with simple GETs. Requiring Authorization forces a CORS preflight we never allow, and the Sec-Fetch-Site guard rejects cross-site outright. Cookie sessions would need SameSite=Strict plus a CSRF token.',
      'A user over budget on an expired snapshot is served stale (200, stale=true) instead of a 429: the data exists and the budget protects GitHub, not the cache. Found during integration.',
      'A dev token is not a security boundary: anyone who can reach the API can mint one, so production must run jwt or tailscale.',
      "Previews and 404 lookups are charged too, so probing random orgs spends the prober's budget, not the shared one. Verified live: mallory spent 91 calls and was refused with a 429 and Retry-After while alice was still served.",
      'Metrics carry no per-user labels to avoid cardinality blow-up; per-user breakdowns come from Loki logs, which carry the principal.',
      'New 401, 403 and 429 problem types enter the contract and the generated client.',
    ],
    revisitWhen:
      'Production goes live: verify gateway JWTs with JWKS rotation and add audit logs; move to per-tenant budgets if users map to teams.',
  },
]

export const roadmap: RoadmapArea[] = [
  {
    area: 'Topology and scaling',
    now: 'One process by default with an in-memory LRU of 256 orgs. A Redis store exists for sharing snapshots and, with it, the rate-limiter buckets, but single-flight, the negative cache, load progress and preview results are per process, so replicas can each refresh the same org and each report its own progress.',
    next: [
      'Run at least two api replicas behind a load balancer, autoscaled on CPU and request latency.',
      'Make Redis the default store and add a distributed single-flight lock: SET key NX PX with a TTL a little above the cold-fetch time, losers poll the snapshot key (or a pub/sub channel) with a bounded wait, then fall back to fetching on timeout.',
      'Share load progress through Redis (progress:{org} with a short TTL) so any replica can answer a poll, and add an optional SSE transport with the same response shape (tel-aw3).',
      'Move the 60s negative cache into Redis.',
      'Size memory: about 8.5k repos (microsoft) is a few MB of JSON per org; set maxmemory with an allkeys-lru policy and alert on evictions.',
      'Keep filtering in memory while orgs stay under tens of thousands of repos; move to Postgres or SQL with indexes on (language, stars) once snapshots are persisted for history or the in-memory sort shows up in p95.',
    ],
    why: "Today's per-process state is fine for one container and wrong for two.",
  },
  {
    area: 'Data freshness',
    now: 'Refresh happens on demand: a request past TTL plus the 60s SWR window waits for revalidation, and a request inside the window triggers one background refresh. PREWARM_ORGS warms the listed orgs at startup and keeps them warm through SWR. A cold org no longer blocks: it returns a provisional first page and progress (ADR-0012).',
    next: [
      'A refresher worker driven by a scheduler that refreshes entries before they expire (refresh-ahead) so users never see a synchronous revalidation, and that owns the prewarm list instead of an environment variable.',
      'GitHub webhooks (repository events) to invalidate or refresh the affected org immediately, with the TTL as the safety net.',
      'Stream progress over SSE rather than polling once more than one replica serves a load (tel-aw3).',
    ],
    why: 'First paint is now 1.5 to 2.8s, but the complete answer for a big cold org still takes 15s or more, so the fix is to make cold loads rare.',
  },
  {
    area: 'GitHub access',
    now: 'One optional personal access token, 5,000 requests an hour with it and 60 without. Concurrency is a setting, 8 with a token. Per-user budgets and a 20% reserve keep one caller from draining it. Stars previews use the separate Search quota.',
    next: [
      'Use a GitHub App: installation tokens are short lived, rotate automatically and have their own per-installation limits.',
      'Add a token pool with a per-token budget scheduler that picks the token with the most remaining quota.',
      'Treat secondary limits as feedback: on a secondary-limit response or Retry-After, lower page concurrency adaptively and recover slowly.',
      'Opt-in eager preview that starts with the walk, trading one extra call for about a second off first paint (tel-625).',
      'Use Search with sort=updated plus filter qualifiers so filtered updated and pushed previews are exact instead of progress only (tel-1w6).',
    ],
    why: 'One shared token is a single point of exhaustion; the per-user budget limits who can drain it, not how big it is.',
  },
  {
    area: 'Security',
    now: 'Authentication exists: every request has a Principal (a dev-minted JWT locally, a gateway JWT or Tailscale identity in production), with per-user request and upstream-spend limits, a cross-site guard, an optional org allowlist, an nginx CSP and security headers, and principal in every log line. The token is a SecretStr with log redaction, and CORS is dev-only.',
    next: [
      'Put a real SSO gateway (oauth2-proxy, Cloudflare Access or Tailscale) in front in production and run AUTH_MODE=jwt or tailscale; the dev mint is not a security boundary.',
      'Rotate credentials: JWKS key rotation on the gateway, short-lived tokens, and GitHub App installation tokens in place of a PAT.',
      'Audit logs: who requested which org, who was refused and why, shipped to durable storage with retention.',
      'Inject secrets at runtime from AWS Secrets Manager, Doppler or 1Password.',
      'Distroless, non-root, read-only-filesystem images, signed with cosign and shipped with an SBOM; Renovate for dependency updates.',
      'Kubernetes network policies allowing api to reach only Redis, the collector and api.github.com.',
    ],
    why: 'Moving from a local demo to a shared service changes who can call it; identity now exists, so the remaining work is making it trustworthy.',
  },
  {
    area: 'Reliability',
    now: 'Retries with full jitter, a pre-flight budget guard, timeouts of 10s per request and serve-stale for up to 24h. There is no memory of a recent upstream failure, so each request past the SWR window retries.',
    next: [
      'Define SLOs: warm p95 under 150ms and 99.9% availability.',
      'Add a circuit breaker around GitHub so an outage stops costing a retry cycle per request.',
      'Set explicit timeout budgets from the route down to each page, and bulkhead the refresher from request serving.',
      'Chaos tests for upstream outages, 5xx storms and slow responses, asserting stale serving.',
      'Graceful degradation stays stale-first.',
    ],
    why: 'Stale-on-error is the best feature of the cache; a breaker makes it cheaper.',
  },
  {
    area: 'Observability',
    now: 'Metrics, traces and JSON logs reach an otel-lgtm container with a provisioned dashboard. Ephemeral and local.',
    next: [
      'An OTel Collector gateway with tail sampling that keeps error and slow traces.',
      'Retention policies per signal.',
      'Alerts: rate-limit remaining under 10%, stale-serve ratio, 5xx burn rate, eviction count.',
      'Browser RUM tied to the backend with trace context.',
      'Exemplars linking latency histograms to traces.',
    ],
    why: 'Dashboards help when someone is looking; alerts help when they are not.',
  },
  {
    area: 'Delivery',
    now: 'No CI by decision. make lint and make test run formatters, type checks, 255 backend and 48 frontend tests and both contract drift checks.',
    next: [
      'CI pipeline: lint, tests, contract drift, Schemathesis against the ASGI app, Playwright end-to-end against compose, image build and vulnerability scan.',
      'Preview environments per pull request.',
      'Canary releases with automatic rollback on the SLO burn rate.',
      'Infrastructure as code with Terraform.',
      'Version the API under /api/v1 with a published deprecation policy.',
    ],
    why: 'The checks exist; they only need a trigger.',
  },
  {
    area: 'Product',
    now: "Browse one org's repositories with language, stars, archived and type filters, sorting, and cursor or offset paging.",
    next: [
      'Stars-over-time history from Postgres snapshots.',
      'Compare several orgs side by side.',
      'Saved views.',
      'CSV export of the filtered list.',
      'Multi-value language filters.',
    ],
    why: 'Snapshots are already complete and content-hashed, which makes history cheap to persist.',
  },
]

export const overview: Overview = {
  title: 'Telescope: design overview',
  paragraphs: [
    "Telescope serves GET /api/orgs/{org}/repos to a React SPA. GitHub's list endpoint cannot filter by language or stars and cannot sort by stars, so the backend walks every public page of an org once, builds an immutable snapshot, and does all filtering, sorting and pagination in memory.",
    'Requests are cheap once a snapshot exists: a warm request takes about 30ms and costs no GitHub quota. A cold fetch is the expensive path (google: 2,946 repos in 30 pages, 13s tokenless at concurrency 4 and 7.3s with a token at concurrency 8; microsoft: 8,474 repos in 85 pages, 33s at concurrency 4), so most of the design protects that path: single-flight, a budget guard, ETag revalidation, stale-while-revalidate and serve-stale-on-error.',
    'Round two changed what a cold load feels like and who pays for it. A cold request no longer blocks: after a 1.5s wait it returns a provisional but exact first page from one cheap upstream call, plus a progress count, and the client polls until the snapshot completes (ADR-0012). Measured with a token: google by stars paints its exact top 30 after 2.8s and completes at 6.5s, where it used to show nothing for 6.5s; kubernetes-sigs by name paints at 1.5s with a free preview and completes at 2.6s; microsoft by updated plus python paints progress at 2.7s and completes at 15.7s. The scarce resource is GitHub quota, not CPU, so it is budgeted per user: each request carries an identity, and the upstream calls a request starts are charged to it, with a global reserve kept for background refreshes (ADR-0013).',
    'The pieces are layered and depend only downwards through small interfaces: GitHubClient (I/O), SnapshotService over a SnapshotStore (memory or Redis), a pure query engine, then the route, which sits behind authentication, a rate limiter and an UpstreamGovernor. Models and errors are dependency-free, openapi.json is generated from them, and the frontend client is generated from openapi.json.',
  ],
  principles: [
    'Contract-first: models.py is the source of truth, openapi.json and the TypeScript types are generated from it, and drift fails a test.',
    'Fetch once, query locally: upstream call count is independent of client traffic.',
    'Never cache partial data: a Snapshot exists only for a complete page walk, so a failed fetch stores nothing.',
    'Degrade to stale rather than fail: any upstream error becomes a 200 with snapshot.stale=true while a copy under 24h old exists, and so does a user who is over budget.',
    'The quota is a budget, per user: rate-limit headers are tracked on every response, a guard refuses a doomed walk after page 1, and upstream spend is charged to the user who starts it, with a global reserve for background refreshes (ADR-0013).',
    'Paint something exact early: a cold load returns a provisional first page and progress instead of blocking, and never shows an approximation as final (ADR-0012).',
    'Observable by default: request ids, JSON logs with trace ids and principal, OpenTelemetry metrics and traces, and a provisioned Grafana dashboard.',
  ],
}
