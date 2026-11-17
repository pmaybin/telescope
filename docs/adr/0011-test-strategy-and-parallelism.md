# ADR-0011: Test strategy and parallelism

- Status: Accepted
- Date: 2026-11-17

## Context
Quality is evaluated locally. Tests must be fast, deterministic and independent of the network and of GitHub's rate limits (60/hour tokenless, ADR-0007). Several agents work in parallel, so tests must not share mutable state. The decisions log #2 chose fixtures first, then a PAT for one final live check.

## Options considered
- **Hit the real GitHub API in tests**: slow, flaky, burns quota, and non-reproducible. Rejected for automated tests (one manual live check at the end is fine).
- **`unittest.mock` patching of httpx**: couples tests to internals. **respx** mocks at the transport level with real `Link` and rate-limit headers. Chosen.
- **Real clocks and sleeps**: slow and flaky for TTL, SWR and backoff. **Injected `now`, `sleep` and `rng`.** Chosen.
- **Serial test runs**: fine at this size, but parallel-safe tests are cheap if designed in. **pytest-xdist.** Chosen.
- **Hypothesis**: adds a dependency. A seeded `random` with parametrisation gives property-style coverage with none.
- **Frontend**: Jest or Vitest (shares the Vite config, ESM-native, chosen); component mocking vs network mocking (MSW at the network layer, so the real client code runs, chosen).

## Decision
**Backend (pytest, `addopts = -n auto`)**
- GitHub client: respx with a fixture builder (`make_repo_json`, N-page mocks with correct `Link` headers). The real API is never called. Covers multi-page walks, normalisation, auth header presence, 404, primary/secondary limits, the budget guard, retry and backoff, failure on page k of N (no snapshot), and ETag revalidation (all 304, one changed).
- Cache: fake fetchers (counting, blocking on an `asyncio.Event`, raising) with an injected clock. Covers TTL, SWR, single-flight (10 concurrent gets -> 1 fetch), stale-on-error, max-stale, the negative cache, LRU, and "nothing stored on error".
- Query engine: pure functions with no I/O. Table-driven filter and sort tests, nulls last in both directions, the id tiebreak, and **property-style walks** on seeded random datasets: forward cursor walks return every item exactly once in order for several limits, backward walks mirror them, and the key row being deleted in a newer snapshot still continues correctly.
- Observability: log lines contain `trace_id` in a span, the token never appears in output, request-id handling, and `configure_otel` is a no-op without the env var. Handlers write to `StringIO`/`caplog`, so nothing is global.
- Contract: the OpenAPI drift test (ADR-0010).
- Rules: no shared module-level mutable state, no real sleeps, no network, injected `now/sleep/rng`.

**Frontend (Vitest + jsdom + Testing Library + MSW 3 + `openapi-msw`)**
- Typed handlers are derived from the same `paths` type as the client, so a contract change breaks the handlers at compile time. Tests assert the query params the handler received (cursor sent, cursor dropped on filter change), and cover loading/empty/404/rate-limited/stale states, null placeholders, and URL updates. The URL and handlers are reset between tests.

**Running**: `make test` runs `test-backend` and `test-frontend` concurrently (`make -j2 --output-sync=target`).

**Optional extra**: **Schemathesis** against the running app or the ASGI app, generating requests from `openapi.json` and checking responses conform. It is not part of the default suite because it can be slow and may need a stubbed upstream.

## Consequences
- Pro: a suite that runs in seconds, offline, with no rate-limit cost, and without ordering dependencies. xdist surfaces hidden shared state immediately.
- Pro: time-dependent logic (TTL, SWR, jitter) is tested deterministically.
- Con: respx fixtures encode our understanding of GitHub's behaviour (e.g. `Link` and rate-limit headers). If it is wrong, tests pass while production fails. The single manual live check with a PAT, plus the research notes, mitigate this.
- Con: injecting clocks, sleeps and rng adds constructor parameters. That is a small price.
- Con: seeded random walks are less thorough than Hypothesis shrinking, but they are dependency-free and reproducible.
- Con: no browser/E2E tests. The UI is covered at component level against a typed network mock.
