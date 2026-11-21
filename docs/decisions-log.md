# Decision / Q&A log

**Timebox start:** 2026-11-17T10:29Z (first human reply to the kickoff questions)
**Feature freeze (3h30m):** 2026-11-17T13:59Z · **Hard stop (4h00m):** 2026-11-17T14:29Z

| # | Time (UTC) | Question | Answer | ADR |
|---|---|---|---|---|
| 1 | 10:29 | Task runner: mise, Makefile or both? | **Makefile + thin mise.** The Makefile holds the real targets; mise pins tool versions and adds aliases. | 0001 |
| 2 | 10:29 | Is a GitHub PAT ready? | **Fixtures first, PAT later.** Develop against respx fixtures; use a PAT for the final live check. | 0011 |
| 3 | 10:29 | Default cache backend and TTL? | **In-memory now, Redis if time.** Cache behind an interface; Redis is a stretch bead. 10 min TTL (architect default). | 0003 |
| 4 | 10:29 | Default pagination mode and sizes? | **Cursor by default.** Offset is a nice-to-have later. **page/per_page cut** for time. Sizes: default 30, max 100 (architect default). | 0004 |
| 5 | 10:30 | Observability depth? | **Dashboard + logs + traces.** | 0009 |
| 6 | 10:30 | Forks / `type`? | **Expose `type`, default `all`.** Return a `fork` flag. | 0002 |
| 7 | 10:30 | Hosting / CI? | **A repo run locally for evaluation; no CI.** The spec-drift check runs as a test/make target instead. | 0010 |
| 8 | 10:30 | Tooling? | **uv + ruff + mypy, pnpm.** | 0001 |

## Architect proposals (10:34Z), defaults applied pending human objection

| # | Proposal | Status | ADR |
|---|---|---|---|
| P1 | One upstream fetch per org, always `type=public`; `all/sources/forks` filtered locally (one quota cost per org, no private-repo leakage with a reviewer's token) | default applied | 0002 |
| P2 | GitHub rate limit → **503** + `Retry-After` (stale data → 200 `stale:true`); a budget guard fails fast before burning quota | default applied | 0006, 0007 |
| P3 | Keyset cursor carrying a snapshot id; on refresh, continue and flag `cursor_from_older_snapshot` | default applied | 0004 |
| P4 | Default `sort=stars desc`; `updated` = `updated_at`; extra `pushed` sort | default applied | 0005 |

## Research outcomes
- r1 (10:35): fetch-all confirmed; google has about 30 pages at per_page=100; **unauthenticated 304s count against the limit** (observed), so ETags only save quota with a token. → ADR 0002/0003/0007
- r2 (10:36): otel-lgtm 0.41.0; datasource UIDs prometheus/loki/tempo; dashboards mount at /otel-lgtm/grafana/conf/provisioning/dashboards/custom. → ADR 0009
- r3 (10:36): openapi-typescript + openapi-fetch; openapi-msw for typed MSW handlers. → ADR 0010

## Wrap-up (10:51Z)
- All beads closed, including both stretch beads (tel-offset, tel-redis). Verified end to end in compose: tokenless and with a PAT, the Redis profile, and the dashboard, logs and traces.
- Secrets scan: the real token is absent from git history and tracked files; the only `ghp_` strings are fake fixtures in the redaction tests.

## Publishing (human answers)
- Commit author email: rewrite to the GitHub no-reply address before the first push.
- Local paths in the prompt log: leave verbatim.
- Repository: pmaybin/telescope (existing, empty, private) → push, then make it public, then submit.

## Round two (branch `feat/progressive-first-page`, started 2026-11-21 09:18Z)

| # | Time (UTC) | Question | Answer | ADR |
|---|---|---|---|---|
| R2-1 | 09:18 | Cold loads are slow; can we show the first page with a spinner for the rest? | Investigate and architect. Measured: one ~1 s upstream call reproduces our first page exactly for every sort (list sort for name/updated/pushed, Search for stars). | 0012 |
| R2-2 | ~09:28 | Minimise GitHub quota: does a cold filtered first request cost the preview plus the seed? | Yes (N + 1). Capped: one preview per cold load per org (`PREVIEW_MODE=first`); `name` asc costs 0 extra; `off` = progress only. | 0012 |
| R2-3 | ~09:32 | Per-user rate limiting / DoS of quota; JWT or CSRF for dev? | Limit **upstream spend** per user, not just request rate; global 20 % reserve; walk concurrency cap. Bearer JWT (CSRF is not applicable to a read-only bearer API); reject `Sec-Fetch-Site: cross-site`. | 0013 |
| R2-4 | 09:36 | Approve? | **Yes for JWTs** (dev-minted; gateway JWT/Tailscale in prod). **Org allowlist off by default.** Record timings, prompts and decisions. | 0013 |
- 09:38Z: delegated tel-7i3 (backend, ADR-0013) and tel-rp6 (frontend/nginx, ADR-0013) to Sonnet subagents at medium effort, in parallel. tel-1xy (ADR-0012 implementation) waits on tel-7i3, because previews are charged to the per-user budget.
- 09:46Z: ADR-0013 integrated. Architect fixes:
  - A user who is over budget on an expired snapshot is now served stale data (200 with `stale: true`) instead of a 429. A test was added.
  - Removed the obsolete `@ts-expect-error` comments after the client was regenerated.
- Live check against real GitHub with the token:
  - no bearer token → 401;
  - `Sec-Fetch-Site: cross-site` → 403;
  - `mallory` spent 6 calls on random orgs (404s) and 85 on microsoft; apache was then refused with 429 `upstream-budget-exceeded` and `Retry-After: 112`, while `alice` was still served;
  - the principal appears in the logs;
  - nginx config passes `nginx -t`.
- Subagent deviations accepted (all safer or test-driven):
  - JWKS fetched with httpx (mockable);
  - right-to-left `X-Forwarded-For`;
  - pages charged once each (retries are not charged);
  - the reserve check runs before the spend check;
  - `/api/dev/token` always appears in the contract (it returns 404 outside dev mode).
- Gates: `make lint` passes; 218 backend and 42 frontend tests pass.
- 09:48Z: delegated tel-1xy (ADR-0012) to backend and frontend Sonnet subagents (medium effort) in parallel, using a shared contract addendum: snapshot.complete/progress, nullable id/fetched_at/repo_count/total, page.provisional_reason.
- 10:09Z: ADR-0012 integrated. Architect changes:
  - **Search previews now request `per_page = limit` instead of 100.** Measured: 100 results took 2.9 s, 30 results about 1 s. Search applies the filters itself, so `limit` results are enough.
  - **Rejected: starting the preview at the start of the cold wait.** It would cut about 1 s more, but it spends a call even when the walk finishes inside the wait (single-page orgs). That conflicts with the human's "minimise GitHub quota". The preview stays lazy: it starts only once the 1.5 s cold wait has expired.
  - Removed the temporary frontend types in favour of the generated client, and fixed fixtures for the required `complete` field.
- Live results with the token, after a cold restart:

  | Org and query | First paint | Complete |
  |---|---|---|
  | google, stars | 2.8 s (exact top 30, total 2,947) | 6.5 s (was 6.5 s of blank) |
  | apache, stars, before the per_page fix | 4.4 s | 6.9 s |
  | kubernetes-sigs, name (free preview) | 1.5 s | 2.6 s |
  | microsoft, updated + python | 2.7 s, then progress 1 → 73 of 85 pages; preview correctly inexact (about 21 % Python) | 15.7 s |

  - A user who had spent 31 calls (google) was refused microsoft (about 86 calls) by the per-user budget, as designed.
- Gates: `make lint` passes; 253 backend and 46 frontend tests pass.
- 10:12Z: Human asked whether testing used up the GitHub credits. Checked `/rate_limit` (which is free): the token had 4,682 of 5,000 core calls left (318 used, mostly cold reloads after restarts) and Search 30 of 30; tokenless had 51 of 60.
- ~10:20Z: Human reported that searching microsoft wouldn't load anything.
  - The API was healthy, and a fresh headless-Chrome load rendered microsoft (8,499 repos).
  - None of the human tab's requests reached the API, which pointed to the frontend auth middleware. Two bugs found, either of which leaves a tab stuck after an API restart or hot reload:
    1. The dev-token mint had no timeout, so a mint caught mid-restart blocked every later request forever.
    2. One 404 from the mint (seen at 10:04 during a hot reload) was remembered forever as "no dev auth".
  - Fixes: a 5 s mint timeout; "no dev auth" now expires after 30 s and is cleared on any 401; two regression tests.
