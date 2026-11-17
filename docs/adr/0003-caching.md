# ADR-0003: Caching

- Status: Accepted
- Date: 2026-11-17

## Context
Every client request would otherwise cost about 30 GitHub calls (ADR-0002) against a 60/hour tokenless budget. The data changes slowly, so a cache is mandatory. The design must also survive upstream failures and stampedes, and keep a path to Redis (decisions log #3: in-memory now, Redis if time, 10 min TTL).

## Options considered
| Technique | Pros | Cons |
|---|---|---|
| In-process TTL + LRU | Zero infra, fastest, trivial to test | Per-process, lost on restart, not shared across workers |
| Redis | Shared, survives restarts, multi-worker | Extra service, serialisation, more failure modes; overkill for a local demo |
| ETag conditional requests | Revalidation instead of refetch; free 304s with a token | **Unauthenticated 304s still count against the limit** (research section 4; observed `x-ratelimit-used` 10 -> 11), so it saves quota only with a token |
| Stale-while-revalidate (SWR) | Hides refresh latency from users | A background task to manage |
| Serve-stale-on-error | An outage or rate limit becomes a degraded 200, not an error | Must flag staleness to the client |
| Single-flight | Stops N concurrent misses becoming N fetches | A little concurrency code |
| HTTP caching headers on our API | Browser/proxy cache, 304s for free | Only helps repeat identical queries |
| Negative caching | Stops repeated lookups of a non-existent org burning quota | Short staleness if the org is created later |

## Decision
Combine the cheap ones behind a small interface.
- `SnapshotStore` Protocol (`get/set/delete`) with an `InMemorySnapshotStore` (dict, LRU bound of 256 orgs). Redis is a stretch bead behind the same Protocol (a commented profile exists in compose).
- `SnapshotService` (key = lower-cased org; age measured from `snapshot.fetched_at`):
  - age < **TTL 600s**: hit.
  - TTL <= age < TTL + **SWR 60s**: return immediately and start one background refresh.
  - older: refresh synchronously, passing `previous` so the client revalidates each page with its stored **ETag** (`If-None-Match`). If every page is 304, the same snapshot (and id) is kept with a new `fetched_at`.
  - On any `UpstreamError`, serve the cached snapshot with `stale=true` while age < **max-stale 24h**. Otherwise re-raise.
  - **Single-flight** per key (a shared task), with errors propagated to all waiters and cleanup in `finally`.
  - **Negative cache**: `OrgNotFound` is remembered for **60s**. A 404 on revalidation also deletes the cached entry (the org is gone).
- Our responses carry a weak `ETag` (snapshot id + normalised query) and `Cache-Control: private, max-age=60`. A matching `If-None-Match` yields 304.
- Metrics: `telescope_cache_lookups_total{result=hit|miss|stale|negative_hit}` (ADR-0009).
- Nothing is stored on error paths, and partial data cannot be stored by construction.

## Consequences
- Pro: steady state costs zero upstream calls. A refresh is at most about 30. Outages and rate limits degrade to stale 200s for up to a day.
- Pro: the interface makes the Redis swap a new class, with no caller changes.
- Con: with no token, ETag revalidation saves nothing (a 304 still costs a request). It is kept because it is free to implement and pays off when a token is configured, and the long TTL is what protects tokenless usage.
- Con: the in-memory store is per process. With several uvicorn workers each fetches independently. That is acceptable for a local demo and is what Redis would fix.
- Con: the SWR window returns `stale=false` data that is slightly past TTL. It is within the documented tolerance, so it is not flagged.
- Con: TTL data can be 10+ minutes behind GitHub. `fetched_at` is exposed so the UI can show it.
