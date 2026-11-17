# Telescope backend

FastAPI (Python 3.12, uv) service behind `GET /api/orgs/{org}/repos`. See the [root README](../README.md) for the API summary and design decisions.

## Module map (`src/telescope/`)

| Module | Role |
|---|---|
| `models.py` | Public contract and domain types (`Repo`, `Snapshot`, `RepoQuery`, `RepoPage`, `RateLimitState`, ...). Source of `openapi.json`. |
| `errors.py` | Domain exceptions (`OrgNotFound`, `UpstreamRateLimited`, ...). |
| `github/` | `GitHubClient`: async page walk with `Link` parsing, bounded concurrency, budget guard, ETag revalidation, jittered retries; `mapping.py` normalises raw repos (`parse_repo`). |
| `cache/` | `SnapshotService` (TTL, stale-while-revalidate, serve-stale, single-flight, negative cache) over a `SnapshotStore`: `InMemorySnapshotStore` or `RedisSnapshotStore`. |
| `query/` | Pure engine: `run_query` filters, sorts and paginates a snapshot; `cursor.py` encodes/decodes keyset cursors and hashes queries. |
| `api/` | `routes.py` (the endpoint, ETag/304, rate-limit headers), `deps.py` (service wiring), `problems.py` (problem+json handlers). |
| `observability/` | `logging.py` (JSON, redaction), `middleware.py` and `context.py` (request id), `otel.py` (setup), `metrics.py` (the only place that touches OTel instruments). |
| `settings.py` | `Settings` (pydantic-settings). |
| `main.py` | `create_app()` and the module-level `app`; `export_openapi.py` writes `openapi.json`. |

## Request flow

```
route (api/routes.py)
  -> SnapshotService.get(org)        cache hit / SWR / single-flight refresh
       -> GitHubClient.fetch_org_repos  (only on miss or refresh; page 1, budget guard, rest concurrently)
  -> run_query(snapshot, RepoQuery)  filter, sort, keyset or offset page
  -> RepoPage (+ ETag, Cache-Control, rate-limit headers)
```

## Settings

Read from the environment, then `../.env` and `.env`. Names are the upper-cased field names.

| Env var | Default | Meaning |
|---|---|---|
| `GITHUB_TOKEN` | unset | Optional PAT (`SecretStr`). Empty counts as unset. |
| `GITHUB_API_URL` | `https://api.github.com` | Upstream base URL |
| `GITHUB_TIMEOUT_S` | `10.0` | Per-request timeout |
| `GITHUB_MAX_RETRIES` | `3` | Retries for 5xx and network errors |
| `GITHUB_PAGE_CONCURRENCY` | `8` | Concurrent page fetches |
| `CACHE_TTL_SECONDS` | `600` | Snapshot freshness |
| `CACHE_BACKEND` | `memory` | `memory` or `redis` |
| `REDIS_URL` | `redis://localhost:6379/0` | Used when `CACHE_BACKEND=redis` |
| `LOG_LEVEL` | `INFO` | Root log level |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | JSON list |

OTel is configured with the standard `OTEL_*` variables (`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, ...); compose sets them for the stack.

## Run locally

```sh
cd backend
uv sync
uv run uvicorn telescope.main:app --reload     # http://localhost:8000/docs
```

Health check: `GET /healthz`. Or from the repo root: `make install`, `make up`.

## Tests

```sh
cd backend && uv run pytest        # parallel by default (-n auto)
```

Layout under `tests/`: `github/` (client with respx, mapping), `cache/` (service, Redis store), `query/` (engine), `api/` (route via ASGI transport), `observability/` (logging, middleware, OTel metrics), `fixtures/github.py` (paginated response builder), plus `test_settings.py`, `test_health.py` and `test_openapi_contract.py` (drift check). No real network, no real sleeps: clock, sleep and RNG are injected.

Quality gate: `uv run ruff check && uv run ruff format --check && uv run mypy src` (strict).

## Logging

One JSON object per line on stdout. Fixed fields: `timestamp`, `level`, `logger`, `message`, `request_id`, `trace_id`, `span_id`. Structured extras vary by event and include `method`, `path`, `route`, `status_code`, `duration_ms`, `org`, `github_path`, `page`, `attempt`, `retry_in_s`, `ratelimit_remaining`, `cache_key`, `age_s`, `slug`. The token and `Authorization` header are redacted by a filter and never logged. uvicorn's access log is disabled in favour of the request middleware.
