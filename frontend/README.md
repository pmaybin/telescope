# Telescope frontend

React + TypeScript (Vite, pnpm). One page that lists a GitHub organisation's repositories via our backend (`GET /api/orgs/{org}/repos`).

## Structure

- `src/api/client.ts`: typed `openapi-fetch` client plus type aliases. The only place that talks to the backend.
- `src/api/schema.d.ts`: generated, do not edit.
- `src/useUrlState.ts`: `URLSearchParams` + `history.pushState` + `popstate` hook. The URL is the state (`org`, `language`, `min_stars`, `archived`, `type`, `sort`, `order`, `limit`, `cursor`). Any update that does not set `cursor` clears it.
- `src/useRepos.ts`: fetch hook; aborts in-flight requests on change and keeps the previous page (dimmed) while loading.
- `src/components/`: `OrgForm`, `Controls`, `DebouncedInput`, `RepoTable`, `ProblemView` (404, invalid cursor, rate limit, 5xx).
- `src/App.tsx`: wires it together (states, banners, pagination, rate-limit footer).
- `src/test/`: MSW server, typed `openapi-msw` handlers and fixtures, test setup.

## Scripts

`pnpm dev` (proxies `/api` to `VITE_API_PROXY_TARGET`, default `http://localhost:8000`), `pnpm build`, `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm fmt` / `pnpm fmt:check`, `pnpm gen:api` / `pnpm gen:api:check`.

## Client generation

`pnpm gen:api` runs `openapi-typescript ../openapi.json -o src/api/schema.d.ts`. The spec is exported from the FastAPI app; `gen:api:check` fails if the committed types have drifted.

## Testing

Vitest + jsdom + Testing Library. The network is faked with MSW (`setupServer`) using `openapi-msw` handlers typed from `schema.d.ts`, so handlers break at compile time if the contract changes. Tests assert on the query params the handler received and on `window.location.search`. The server starts at setup import time (so fetch is patched before the client captures it); handlers and the URL are reset after each test. Unhandled requests fail the test.
