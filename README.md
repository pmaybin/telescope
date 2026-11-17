<img src="assets/icon.svg" width="64" height="64" alt="">

# Telescope

Telescope is a small internal-tool-style explorer for a GitHub organisation's public repositories. A FastAPI backend (`GET /api/orgs/{org}/repos`) fetches an org's repos from the GitHub REST API once, caches them as an immutable snapshot, and serves filtered, sorted and paginated pages from memory. A React + TypeScript UI sits on top, and OpenTelemetry feeds a provisioned Grafana dashboard. It was built as a timeboxed take-home and is meant to be cloned and run locally.

Created in [T3 Code](https://t3.codes).

## Quick start

**Prerequisites:** Docker with Compose v2, and `make`. For the local dev and test loop you also need uv, Node 22 and pnpm 10, or simply run `mise install` (versions are pinned in `mise.toml`).

```sh
cp .env.example .env     # optional: set GITHUB_TOKEN (fine-grained PAT, public repositories, read-only)
make up                  # build and start the stack
```

| What | URL |
|---|---|
| Web UI | http://localhost:8080 |
| API docs (Swagger) | http://localhost:8000/docs |
| Grafana (dashboard "Telescope") | http://localhost:3000 |

Host ports can be overridden with `WEB_PORT`, `API_PORT` and `GRAFANA_PORT` (for example `API_PORT=18000 make up`; pass the same variables to `make down`/`make logs`).

**With and without a token.** Both work. Tokenless GitHub access allows 60 requests/hour, and a large org like `google` costs about 30 requests (one per page of 100) for a cold fetch. To avoid burning the quota on a fetch that cannot finish, the client has a **budget guard**: after reading page 1 it knows how many pages the org needs, and if the remaining quota is too small it refuses up front with `503` + `Retry-After` and `pages_needed` instead of fetching half. Successful fetches are cached as a snapshot (TTL 600s, see below), so repeat requests cost no GitHub calls.

**Redis cache (optional).** The default cache is in-memory. To share it through Redis, enable the compose profile and select the backend:

```sh
CACHE_BACKEND=redis COMPOSE_PROFILES=redis make up
# equivalent to:
CACHE_BACKEND=redis docker compose -f infra/docker-compose.yml --env-file .env --profile redis up -d --build
```

(`CACHE_BACKEND` may also be put in `.env`. `REDIS_URL` is already set to `redis://redis:6379/0` in the compose file.)

## Where the token goes

`.env` (git-ignored) -> `docker compose --env-file .env` -> the `api` container environment -> `Settings.github_token` (a pydantic `SecretStr`) -> the `Authorization` header on GitHub requests. The token is never baked into an image, and a logging filter redacts it from log output. In production, inject `GITHUB_TOKEN` from Doppler, 1Password Connect or AWS Secrets Manager rather than a file ([ADR-0008](docs/adr/0008-secrets.md)).

## Make targets

`make help` prints these. Each mise task is a thin alias (`mise run <target>`).

| Target | What it does | mise |
|---|---|---|
| `make help` | Show help | |
| `make install` | `uv sync` and `pnpm install` | `mise run install` |
| `make up` | Build and start the stack with Docker Compose | `mise run up` (also `mise run run`) |
| `make down` | Stop the stack | `mise run down` |
| `make logs` | Tail stack logs | `mise run logs` |
| `make test` | Backend and frontend tests, concurrently | `mise run test` |
| `make test-backend` | `pytest` (parallel, `-n auto`) | `mise run test-backend` |
| `make test-frontend` | Vitest | `mise run test-frontend` |
| `make lint` | ruff, ruff format check, mypy --strict, ESLint, Prettier check, tsc, generated-client drift check | `mise run lint` |
| `make fmt` | Auto-format backend and frontend | `mise run fmt` |
| `make openapi` | Export `openapi.json` | `mise run openapi` |
| `make gen-client` | Regenerate `openapi.json` and the typed TS client | `mise run gen-client` |

`make lint test` is the quality gate (there is no CI by design). Run it through `mise exec -- make ...` if pnpm is not on your PATH.

## API

`GET /api/orgs/{org}/repos`: full semantics in [docs/design/api-contract.md](docs/design/api-contract.md); machine-readable spec in [openapi.json](openapi.json).

| Param | Type | Default | Notes |
|---|---|---|---|
| `org` (path) | string | | GitHub login |
| `language` | string | all | Case-insensitive exact match. `none` matches repos with no language |
| `min_stars` | int >= 0 | | Inclusive |
| `archived` | bool | both | |
| `type` | `all` / `sources` / `forks` | `all` | Local filter on the `fork` flag |
| `sort` | `stars` / `updated` / `pushed` / `name` | `stars` | |
| `order` | `asc` / `desc` | `desc` (`asc` for `name`) | |
| `limit` | int 1-100 | 30 | |
| `cursor` | opaque string | | From `page.next_cursor` / `page.prev_cursor` |
| `offset` | int 0-100000 | | Offset mode; mutually exclusive with `cursor` |

```sh
curl 'http://localhost:8000/api/orgs/google/repos?language=Go&min_stars=1000&sort=stars&limit=2'
```

```jsonc
{
  "org": "google",
  "items": [{ "id": 1, "name": "…", "full_name": "google/…", "stars": 12345, "language": "Go",
              "license": { "spdx_id": "Apache-2.0", "name": "Apache License 2.0" }, "topics": [], "pushed_at": "…" }],
  "page": { "limit": 2, "total": 41, "has_next": true, "has_prev": false,
            "next_cursor": "eyJ2IjoxLC…", "prev_cursor": null, "offset": null },
  "snapshot": { "id": "…", "fetched_at": "…", "repo_count": 2946, "stale": false,
                "cursor_from_older_snapshot": false },
  "rate_limit": { "authenticated": true, "limit": 5000, "remaining": 4970, "reset_at": "…" }
}
```

Errors are `application/problem+json` (RFC 9457) with `type`, `title`, `status`, `detail`, `instance`, `request_id` and extensions:

| Situation | Status | slug | Extras |
|---|---|---|---|
| Bad query param | 422 | `validation-error` | `errors` |
| Bad or mismatched cursor | 400 | `invalid-cursor` | |
| `cursor` and `offset` together | 400 | `invalid-pagination` | |
| Org not found | 404 | `org-not-found` | `org` |
| GitHub rate limit, or budget guard, no stale data | 503 + `Retry-After` | `upstream-rate-limited` | `retry_after`, `rate_limit`, `pages_needed` (guard) |
| GitHub 5xx or network failure, no stale data | 502 | `upstream-unavailable` | |
| GitHub timeout, no stale data | 504 | `upstream-timeout` | |

If a stale snapshot exists, upstream failures are served as `200` with `snapshot.stale: true` instead.

Headers: `ETag` (weak; `If-None-Match` gives `304`), `Cache-Control: private, max-age=60` (`no-cache` when stale), `X-Request-ID`, and `X-GitHub-RateLimit-Limit` / `-Remaining` / `-Reset` when known.

## Key design decisions and trade-offs

All ADRs live in [docs/adr](docs/adr/README.md); the human Q&A is in [docs/decisions-log.md](docs/decisions-log.md).

- **Fetch all, then filter locally** ([0002](docs/adr/0002-github-data-acquisition.md)). GitHub's list endpoint has no server-side filters, and the Search API is capped at 1,000 results, so we walk every page once and filter, sort and paginate in memory.
- **One upstream dataset per org, `type=public`** ([0002](docs/adr/0002-github-data-acquisition.md)). `type` (`all`/`sources`/`forks`) is a local filter, so it never multiplies upstream calls, and a reviewer's token that can see private repos cannot leak them.
- **Snapshot cache** ([0003](docs/adr/0003-caching.md)). TTL 600s, stale-while-revalidate 60s, serve stale for up to 24h if upstream fails, single-flight per org, and ETag revalidation upstream. Conditional requests only save quota with a token: unauthenticated 304s still count against the limit (measured).
- **Keyset cursors by default, plus offset mode** ([0004](docs/adr/0004-pagination.md)). The snapshot id is a content hash. If the data refreshed since a cursor was issued, we continue by keyset and set `snapshot.cursor_from_older_snapshot`. `page`/`per_page` was cut by decision: it adds little over offset.
- **Null and missing data** ([0005](docs/adr/0005-null-and-missing-data-semantics.md)). Nulls sort last regardless of direction, empty strings become null at ingestion, `id` ascending is the tiebreaker (total, stable order), and `language=none` selects repos without a language.
- **Errors** ([0006](docs/adr/0006-error-handling.md), [0007](docs/adr/0007-rate-limits-and-tokens.md)). problem+json throughout. The upstream limit is **503 with `Retry-After`, not 429**: the client did nothing wrong, our dependency is limited. The budget guard fails fast before burning quota.
- **Bounded concurrent page fetch (8)** ([0002](docs/adr/0002-github-data-acquisition.md)). This deliberately deviates from GitHub's "make requests serially" guidance because a cold 85-page org is otherwise unusable. Concurrency is capped, retries are jittered, and the default was raised from 4 to 8 after measuring real page latency (`GITHUB_PAGE_CONCURRENCY`).
- **Observability** ([0009](docs/adr/0009-observability.md)). OpenTelemetry traces, metrics and logs flow to the `grafana/otel-lgtm` container; JSON logs carry request and trace ids; a metrics facade keeps OTel out of business code; the dashboard is provisioned.
- Also: [0001](docs/adr/0001-architecture-repo-layout-and-tooling.md) tooling, [0008](docs/adr/0008-secrets.md) secrets, [0010](docs/adr/0010-api-contract-and-client-codegen.md) contract and codegen, [0011](docs/adr/0011-test-strategy-and-parallelism.md) tests.

## Measured results

From the architect's end-to-end run on 2026-11-17:

- `google`: 2,946 repos in 30 pages. Cold fetch **13s tokenless** (concurrency 4), **7.3s with a token** (concurrency 8). Warm requests take about 30ms.
- `microsoft`: 8,474 repos in 85 pages, 33s cold at concurrency 4.
- Tokenless with 17 requests left, `microsoft` was refused up front with `503` and `pages_needed: 85` after one request.
- No token string appeared in the container logs.
- The Grafana dashboard shows HTTP RED metrics, cache, GitHub calls, rate limit, logs and traces.

## Testing

The GitHub integration is tested without ever calling the real API:

- **respx** mocks at the httpx transport level, so the real client code path runs.
- A **fixture builder** (`backend/tests/fixtures/github.py`) produces realistic paginated responses with correct `Link` headers.
- **Injected sleep, clock and RNG** make retries, backoff and TTL/SWR behaviour deterministic and instant (no real sleeps).

Backend tests run in parallel (`pytest -n auto` via `addopts`). The frontend suite (Vitest + MSW with typed `openapi-msw` handlers) runs concurrently with the backend from `make test`. Contract drift checks fail if `openapi.json` or the generated TS client are stale (`test_openapi_contract.py`, `pnpm gen:api:check`).

Current counts from `mise exec -- make test`: **162 backend tests** (about 2s) and **14 frontend tests**, all passing.

## What I didn't get to, and how I'd approach it

- **Schemathesis** property tests against `openapi.json`.
- **Cross-replica single-flight** (a Redis lock) and **refresh-ahead / warm-up** for popular orgs. Today single-flight is per process.
- **Progressive first load for huge orgs:** stream page 1 early, or return `202` plus polling.
- **GitHub App auth** for higher rate limits.
- **Webhook-driven invalidation** instead of TTL only.
- **Alert rules**, for example rate-limit remaining under 10%.
- **Browser OTel/RUM.**
- **Playwright e2e** against the compose stack.
- **CI.** Not wanted for this local evaluation; `make lint test` is the gate.
- **`page`/`per_page` mode.** Cut by decision because it adds little over offset.
- **Multi-value language filters.**
- **Auth for the internal tool** (an SSO proxy in front).

## How this was built

An AI-assisted workflow: an architect model coordinated subagents, each owning a bead and a set of files, with the architect reviewing and committing. The artefacts are in the repo:

- Every prompt: [docs/prompts/prompt-log.csv](docs/prompts/prompt-log.csv)
- The kickoff prompt: [docs/prompts/00-architect-kickoff.md](docs/prompts/00-architect-kickoff.md)
- Decisions and Q&A: [docs/decisions-log.md](docs/decisions-log.md)
- Work tracking with beads: [.beads/](.beads/)

**Time spent:** started 2026-11-17 10:29 UTC.
Finished: 2026-11-17 10:51 UTC (about 25 minutes of wall-clock time against a 4-hour timebox; the parallel subagents did most of the implementation)

## Repo layout

```
.
├── backend/    FastAPI app (src/telescope), tests, Dockerfile; see backend/README.md
├── frontend/   React + Vite UI (src), nginx Dockerfile
├── infra/      docker-compose.yml, Grafana dashboard and provisioning
├── docs/       adr/, design/api-contract.md, research/, prompts/, decisions-log.md
├── scripts/    log_prompt.py (prompt log helper)
├── assets/     icon
├── .beads/     issue tracking
├── openapi.json  committed API contract (source for the TS client)
├── Makefile    source of truth for dev tasks
├── mise.toml   pinned tool versions and task aliases
└── .env.example
```
