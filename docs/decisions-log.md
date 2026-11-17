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
