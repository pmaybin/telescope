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
