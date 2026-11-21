# Research: getting the first page quickly on a cold load

Date: 2026-11-21 (round two, branch `feat/progressive-first-page`). Probe script run against live GitHub for `google` (2,947 public repos), compared with our own complete snapshot.

## Where the cold time goes
- Every page of `GET /orgs/{org}/repos?per_page=100` takes **about 1.0–1.4 s** and is about 550 KiB of JSON, with or without a token.
- Page 1 is fetched on its own first, because its `Link: rel="last"` header gives the page count. The remaining pages are then fetched at concurrency 8.
- Cold time is therefore roughly `t(page 1) + ceil((pages - 1) / 8) × t(page)`. For google that is about 1.3 s + 4 × 1.2 s ≈ 6–7 s, which matches the measured 7.3 s.
- For microsoft (85 pages) at concurrency 8 it is about 1.3 + 11 × 1.2 ≈ 15 s.
- The user sees nothing until the last page arrives. That is the real problem: the total time is acceptable for a one-off; the blank wait is not.

## Can the first page be known before the snapshot is complete?
Our sorts are global over every repo, so in general the answer is no: the top 30 by stars could be on any upstream page. But GitHub can sort for us on other endpoints, and a single call takes about 1 s:

| Our sort | Upstream call that returns the same first page | Auth | Quota | Measured | Matches our snapshot |
|---|---|---|---|---|---|
| `name` | `GET /orgs/{org}/repos?sort=full_name&direction=asc|desc` (page 1 of our own walk, for asc) | either | core | 1.26 s | yes (30/30, same order) |
| `updated` | `GET /orgs/{org}/repos?sort=updated&direction=desc` | either | core | 1.10 s | yes (30/30, same order) |
| `pushed` | `GET /orgs/{org}/repos?sort=pushed&direction=desc` | either | core | 1.02 s | yes (30/30, same order) |
| `stars` | `GET /search/repositories?q=org:{org} fork:true&sort=stars&order=desc` | either | **search** (10/min anon, 30/min token) | 0.75–1.1 s | yes (30/30, same order) |
| `stars` (alt) | GraphQL `organization.repositories(orderBy: STARGAZERS)` | **token only** (403 anon) | graphql points | 1.41 s, 22 KiB | yes (30/30, same order) |

Further notes:
- **Search** can also express our filters as qualifiers: `language:`, `stars:>=N`, `archived:true|false`, and `fork:only` or `fork:true`. Its `total_count` (2,947) matched the snapshot, so it can provide an exact filtered `total` too. It is backed by an index and may lag the list endpoint by minutes, so results are *provisional* by definition. Our `language=none` has no reliable qualifier, so that filter falls back to the progress-only view.
- **List endpoints with filters**: if the upstream page has at least `limit` matches after local filtering, its matches are an exact prefix of our ordering, because GitHub ordered them by the same key. Otherwise we can't be sure (a selective filter may need many pages), so we fall back to the progress-only view.
- **GraphQL** is 25× smaller per page but uses sequential cursors, so a full walk would take about 30 × 1.4 s, which is slower than the parallel REST walk. It is useful only as an authenticated preview, and Search already covers that case in both modes. Not adopted.
- **Ascending `updated`/`pushed`** puts nulls first on GitHub, but we put nulls last. For those combinations the list preview isn't exact unless the page holds no nulls; we check this per page.

## Making the full walk itself faster (independent levers)
- Higher concurrency for authenticated requests (for example 16) would roughly halve microsoft's time. GitHub discourages heavy concurrency (secondary limits), so make it opt-in per mode, not the default.
- Pre-warming configured orgs at startup (`PREWARM_ORGS=google,microsoft`), together with the existing SWR, means popular orgs are never cold for users.
- Progress is known early: after page 1 we know `pages_total`, so a real progress bar (`pages_done / pages_total`) is possible instead of an indefinite spinner.

## Post-implementation measurements (2026-11-21 10:09Z)
- Search `per_page=100` took **2.9 s** inside the app (while the walk was running), while `per_page=30` took about 1 s in the probe. Previews therefore request `per_page=limit`, which is safe because Search applies the filters as qualifiers.
- First paint is `cold wait (1.5 s) + preview (about 1–1.3 s)` ≈ 2.7–2.8 s. Starting the preview at the beginning of the cold wait would give about 1.5 s, but costs a call even for orgs whose walk finishes inside the wait. That was rejected to keep GitHub usage minimal; it could be revisited as an opt-in setting.
- A filtered list preview is often inexact (microsoft `updated` + `python`: about 21 of the 100 most recently updated repos are Python, fewer than 30). The progress-only view covers that case. Using Search with `sort=updated` plus qualifiers could make these previews exact; follow-up.
