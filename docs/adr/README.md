# Architecture Decision Records

MADR-style records for telescope. All are **Accepted** as of 2026-11-17. See also `docs/decisions-log.md` (Q&A with the human) and `docs/research/`.

| # | Title | One-line decision |
|---|---|---|
| [0001](0001-architecture-repo-layout-and-tooling.md) | Architecture, repo layout and tooling | Monorepo, FastAPI + React/Vite, uv/ruff/mypy + pnpm, Makefile as source of truth with thin mise aliases, no CI |
| [0002](0002-github-data-acquisition.md) | GitHub data acquisition | Fetch all public repos once (`type=public`, `sort=full_name`, 4 concurrent pages), filter locally |
| [0003](0003-caching.md) | Caching | In-memory `SnapshotStore`, TTL 600s + SWR 60s + max-stale 24h, single-flight, ETags, negative cache |
| [0004](0004-pagination.md) | Pagination | Keyset cursor by default; offset is a stretch; page/per_page cut |
| [0005](0005-null-and-missing-data-semantics.md) | Null and missing-data semantics | Empty -> null, nulls last, id tiebreak, language `none`, name casefold |
| [0006](0006-error-handling.md) | Error handling | problem+json, status table, jittered retries, serve stale, 503 for upstream limits |
| [0007](0007-rate-limits-and-tokens.md) | Rate limits with and without a token | 60 vs 5,000/h, budget guard, rate-limit state in responses |
| [0008](0008-secrets.md) | Secrets | `.env` + `.env.example`, `SecretStr`, redaction, secrets manager in prod, fine-grained PAT |
| [0009](0009-observability.md) | Observability | OTel -> otel-lgtm, JSON logs with trace/request ids, metric facade, provisioned dashboard |
| [0010](0010-api-contract-and-client-codegen.md) | API contract and client codegen | Committed `openapi.json`, openapi-typescript + openapi-fetch, drift checks |
| [0011](0011-test-strategy-and-parallelism.md) | Test strategy and parallelism | xdist, respx, injected clock/sleep/rng, Vitest + MSW, concurrent `make test` |
