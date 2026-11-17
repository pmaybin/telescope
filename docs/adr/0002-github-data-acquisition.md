# ADR-0002: GitHub data acquisition

- Status: Accepted
- Date: 2026-11-17

## Context
The API must filter by language and minimum stars, sort by stars/updated/pushed/name, and paginate, over an org's repositories (google has about 2.9k, roughly 30 pages of 100). GitHub's `GET /orgs/{org}/repos` supports only `type`, `sort` (created/updated/pushed/full_name), `direction` and paging. It cannot filter by language or stars, and it cannot sort by stars ([docs](https://docs.github.com/en/rest/repos/repos#list-organization-repositories); research `docs/research/github-api.md` section 1). Unauthenticated callers get 60 requests/hour, so upstream usage must be frugal (ADR-0007).

## Options considered
1. **Pass-through**: map our params to GitHub's and forward the page. Cheapest per request, but language, stars and star-sorting are impossible, and every client page costs a GitHub call. Rejected.
2. **Search API** (`/search/repositories`, `org:x language:y stars:>=n`). Server-side filters and stars sorting, but results are capped at 1,000, the limit is 10 requests/min unauthenticated, there is no `language:none`, and no `updated` qualifier ([docs](https://docs.github.com/en/rest/search/search#search-repositories)). It cannot represent the full contract. Rejected.
3. **GraphQL** (`Organization.repositories`). About 1 point per 100 nodes ([limits](https://docs.github.com/en/graphql/overview/rate-limits-and-node-limits-for-the-graphql-api)), but a token is required, and I could not verify any language or stars filter. It also excludes tokenless use. Rejected as the default.
4. **Fetch-all-then-filter (REST)**: pull every public repo once, build an immutable snapshot and do all filtering, sorting and pagination locally. Costs about 30 calls per refresh for the largest realistic org, then zero per client request. Chosen.

**Page fetching**: serial vs bounded concurrency.
- Serial: GitHub advises against concurrent requests to avoid secondary limits ([best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)), and it is the safest. But 30 sequential round trips of about 300ms each take about 9s on a cold cache.
- Bounded concurrent (4): cold fetch is about 2-3s. The risk is tripping the secondary rate limit.

## Decision
- Request: `GET /orgs/{org}/repos?type=public&sort=full_name&direction=asc&per_page=100&page=N`, with `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28` and a `User-Agent`.
- `type=public` is always sent, so a reviewer's token that can see private repos never leaks them (contract doc). `sort=full_name` gives a deterministic, contiguous order, so page N's ETag and rows are stable, which makes per-page revalidation work (ADR-0003).
- The API `type` param (all/sources/forks) is a **local** filter on the `fork` flag. It never multiplies upstream datasets.
- Walk: fetch page 1, read `rel="last"` from the `Link` header to learn N, then fetch pages 2..N with concurrency 4 (a semaphore under `asyncio.TaskGroup`). If `last` is missing but `next` is present, follow `next` serially. We never build page URLs ourselves.
- **Concurrency trade-off, stated plainly:** we deviate from GitHub's guidance to prefer serial requests, in exchange for cold-start latency. Mitigations: a small cap (4), honouring `retry-after` and the secondary-limit handling in ADR-0006/0007, and `github_page_concurrency` as a setting, where 1 restores serial behaviour. A failure on any page fails the whole fetch and cancels the siblings.
- A `Snapshot` is built only from a complete walk. Partial data is never representable.

## Consequences
- Pro: the full filter/sort contract is supported with identical semantics for any org size, and the upstream call count is independent of client traffic.
- Pro: filtering and sorting are pure, fast and unit-testable (ADR-0011).
- Con: first request for a large org is slow (seconds) and costs about 30 quota units; tokenless that is half the hourly budget (ADR-0007).
- Con: memory is O(repos per org) per cached org. This is fine for the scale here, and bounded by the LRU in ADR-0003.
- Con: data can be up to the TTL old. We expose `snapshot.fetched_at` and `stale` so that is visible.
- A 404 on `/orgs/{org}/repos` is treated as org-not-found. A `/users/{name}/repos` fallback was considered and left out of scope.
