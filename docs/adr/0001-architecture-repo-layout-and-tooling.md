# ADR-0001: Architecture, repo layout and tooling

- Status: Accepted
- Date: 2026-11-17

## Context
"telescope" is a timeboxed (4h) take-home. It serves `GET /api/orgs/{org}/repos` to a React UI, from GitHub's public API. The reviewer will run it locally. There is no hosting target and no CI (decisions log #7). The work is split across parallel agents, so directory ownership has to be clean. Tooling must give one obvious command per task, and the contract has to stay in sync between backend and frontend.

## Options considered
**Repo shape**
- Polyrepo: needless ceremony for one API and one UI.
- Monorepo with `backend/ frontend/ infra/ docs/`: one clone, one `make` entrypoint, atomic contract changes. Chosen.

**Backend stack**
- FastAPI + httpx + Pydantic v2: async I/O fits the page fan-out (ADR-0002), the OpenAPI spec comes for free (ADR-0010), and Pydantic gives validation and typed models. Chosen.
- Flask/Django: sync by default, no generated contract.
- aiohttp: no spec generation, and weaker typing of the contract.

**Frontend stack**
- React + Vite + TypeScript, pnpm: a fast dev loop and Vitest shares the Vite config. No router, state or query libraries: URL state plus one hook is enough for one page.
- Next.js: SSR is unnecessary and adds a server runtime.

**Python tooling**: uv (fast, lockfile, `--frozen` in Docker), ruff (lint and format in one tool), mypy `--strict`. Poetry/pip-tools and black+flake8 were rejected as slower and more tools to pin.

**Task runner**
- Makefile only: universal, but it does not pin tool versions.
- mise only: pins versions, but its task syntax is less portable and less well known.
- Makefile as the source of truth plus thin mise aliases: chosen (decisions log #1). `mise.toml` pins python 3.12, node 22, uv and pnpm, and each mise task is just `make <target>`, so the two cannot drift.

**CI**
- GitHub Actions: it would never run, because the repo is evaluated locally.
- No CI: checks are `make` targets that a reviewer can run in one command. Chosen.

## Decision
- Layout: `backend/` (`src/telescope/{api,github,cache,query,observability}`, `models.py`, `errors.py`), `frontend/`, `infra/` (compose, Grafana), `docs/` (ADRs, research, design, decisions log), `openapi.json` at the root.
- `models.py` is dependency-free (no httpx or FastAPI) and holds the contract and domain types. `errors.py` holds the domain exceptions. This keeps the GitHub client, cache and query engine decoupled and testable in isolation.
- Layering: client (I/O) -> cache service -> pure query engine -> API route. Each layer depends only downwards, on interfaces (`Fetcher`, `SnapshotStore`).
- Makefile targets: `install up down logs test test-backend test-frontend lint fmt openapi gen-client`. `make lint` runs ruff check, ruff format --check, mypy, eslint, prettier --check, tsc and `pnpm gen:api:check`. The last of these is the drift check.
- The pytest drift test (ADR-0010) runs in `make test`.
- Python 3.12, Node 22, `mise exec -- make ...` where pnpm is not on PATH.

## Consequences
- Pro: one command per task and one place to look; mise adds no logic, so there is nothing to keep in sync.
- Pro: strict typing and lint gates are enforced locally, standing in for CI.
- Con: no CI means nothing blocks a bad push. This is accepted because the evaluator runs `make lint test` themselves. Adding a workflow that calls the same targets would be trivial.
- Con: Make is awkward on Windows. This is acceptable, as the target is Linux/macOS (and Docker).
- Con: a monorepo shares one lockfile policy per language, but there are two lockfiles (`uv.lock`, `pnpm-lock.yaml`) to keep committed.
