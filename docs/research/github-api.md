# GitHub API research (tel-r1)

Sources: docs.github.com unless noted. "Empirical" = one of 3 unauthenticated probes made on 2026-11-17.

## 1. GET /orgs/{org}/repos
- Params (https://docs.github.com/en/rest/repos/repos#list-organization-repositories):
  - `type`: all (default), public, private, forks, sources, member
  - `sort`: created (default), updated, pushed, full_name
  - `direction`: asc|desc; default asc for full_name, else desc
  - `per_page`: default 30, max 100 (larger values silently clamped: https://docs.github.com/en/rest/using-the-rest-api/using-pagination-in-the-rest-api)
  - `page`: default 1
- Link header (pagination doc): `<url>; rel="next", <url>; rel="last"`, also prev/first. Some may be missing (prev on page 1; last if not computable). Docs say do not construct page URLs manually; follow Link.
  - Empirical: `google` per_page=100 gives rel=next and rel=last (page=30, so ~2.9k repos). Link URLs use `/organizations/{id}/repos`.
- Hard page cap: none documented for this endpoint (pagination doc silent).
- Auth: reference page states no requirement; public orgs are readable unauthenticated (empirical: 200 for google, 60/h limit applies).
- Org name is a user: 404. Empirical body for `torvalds`:
  `{"message":"Not Found","documentation_url":"https://docs.github.com/rest/repos/repos#list-organization-repositories","status":"404"}`
  - A 404 also covers private/unauthorised resources (https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api). Fallback: `GET /users/{user}/repos` (not researched here).

## 2. Primary rate limits
(https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
- Headers: `x-ratelimit-limit`, `-remaining`, `-used`, `-reset` (UTC epoch seconds), `-resource` (e.g. core).
- Unauthenticated: 60 req/h. Authenticated: 5,000/h (per task brief).
- Exceeded: "you will receive a `403` or `429` response, and the `x-ratelimit-remaining` header will be `0`." Docs do not specify the primary-limit body.
- "If the `retry-after` response header is present, you should not retry your request until after that many seconds has elapsed."
- Docs warn that continuing to request while limited may get the integration banned.

## 3. Secondary rate limits
- Detection: 403 or 429 with an error message saying a secondary limit was exceeded; status cannot be queried.
- Backoff: honour `retry-after`; else if `x-ratelimit-remaining` is 0 wait until `x-ratelimit-reset`; else "wait for at least one minute"; on repeated failure exponential backoff, then give up after N retries.

## 4. Conditional requests
(https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
- Save `etag`, send as `if-none-match`; unchanged data returns 304.
- Docs: a 304 "does not count against your primary rate limit" only when "the request was made while correctly authorized with an `Authorization` header". The docs are silent on unauthenticated 304s.
- Empirical (unauth): the 304 DID count; `x-ratelimit-used` went 10 -> 11. Do not rely on ETags to save budget without a token.
- ETags are per URL, so each page (with its per_page/type/sort) has its own ETag. Link headers are returned on 200; docs are silent on Link on 304 (304 had no Link in the probe's filtered output; cache it from the 200). Keep per-page ETag + body + Link cached.
- ETags are weak (`W/"..."`); send back verbatim.

## 5. Alternatives
- Search API (https://docs.github.com/en/rest/search/search#search-repositories): 1,000 results max per search; 30 req/min auth, 10/min unauth; separate from core limit; per_page max 100; sort stars|forks|help-wanted-issues|updated.
- Qualifiers (https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories): `org:`, `language:`, `stars:>=n`, `archived:false`, `fork:true` to include forks (excluded by default). No documented `language:none`; no `updated` qualifier (only `pushed`). So "no language" can't be queried and >1,000 matches are truncated. Search is a poor fit.
- GraphQL (https://docs.github.com/en/graphql/overview/rate-limits-and-node-limits-for-the-graphql-api): authenticates via token/App/OAuth (docs' examples all use Authorization; no unauthenticated use documented, so assume token required). 5,000 points/h; cost = requests / 100 (min 1), so 100 repos per page ~ 1 point; first/last 1-100; 500k node cap. Organization.repositories supports orderBy and isArchived/isFork-type args but, to my knowledge, no language or stars filter (reference page not verifiable via fetch; unconfirmed).
- Conclusion: fetch-all-then-filter-locally is the right default. ~30 REST pages for google (~30 of 60/h unauth; ~0.6% of 5,000 authed), cached with a TTL. Without a token, a full refresh uses half the hourly budget.

## 6. Repo fields (reference schema, minimal-repository)
- Non-null/required: name, full_name, html_url, fork.
- Nullable: `description`, `language`, `license` (object with key, name, spdx_id, url, node_id; `spdx_id` can itself be null/"NOASSERTION" in practice), `updated_at`, `pushed_at`.
- Not marked nullable but treat defensively: stargazers_count, forks_count, open_issues_count, archived, topics (array, may be empty), visibility.
- Language filter "none" = `language is null`.

## 7. Gotchas
- `pushed_at` = last push to any branch (search docs: `pushed` = most recent commit on any branch); `updated_at` changes on any repo metadata change (stars, issues, settings) and so is noisier. Sort "updated" in the API = `updated_at`. This `updated_at` semantics is from general knowledge, not a quoted doc.
- `X-GitHub-Api-Version` (https://docs.github.com/en/rest/about-the-rest-api/api-versions): supported 2026-03-10 and 2022-11-28 (support to 2028-03-10); default if omitted is 2022-11-28. Pin explicitly.
- Send `Accept: application/vnd.github+json` and a User-Agent.

## Recommendations
- Fetch all pages with `per_page=100`, `type=public`, following `Link rel="next"` (never build URLs); cache the full list in memory with TTL (e.g. 10-15 min) and filter/sort/paginate locally.
- Send `X-GitHub-Api-Version: 2022-11-28` (stable; or 2026-03-10 after testing) and a token when configured.
- With a token, revalidate pages using ETag/If-None-Match (free 304s). Without a token, treat 304 as costing a request; use long TTL, serve stale on errors.
- Track `x-ratelimit-remaining/reset`; on 403/429 follow retry-after, then reset, then >=60s with exponential backoff; serve stale cache and return 503/429 with Retry-After to clients.
- On 404, optionally fall back to `/users/{name}/repos`; otherwise return 404.
- Treat null description/language/license/dates as normal; `language=none` means null language; map `sort=updated` explicitly (updated_at vs pushed_at).
- Avoid Search (1,000 cap, no language-none, 10/min unauth) and GraphQL (token required, no server-side language/star filters).
