# Telescope frontend

React + TypeScript (Vite, pnpm). One page that lists a GitHub organisation's repositories via our backend (`GET /api/orgs/{org}/repos`).

## Structure

- `src/api/client.ts`: typed `openapi-fetch` client plus type aliases. The only place that talks to the backend.
- `src/api/schema.d.ts`: generated, do not edit.
- `src/useUrlState.ts`: `URLSearchParams` + `history.pushState` + `popstate` hook. The URL is the state (`org`, `language`, `min_stars`, `archived`, `type`, `sort`, `order`, `limit`, `cursor`). Any update that does not set `cursor` clears it.
- `src/useRepos.ts`: fetch hook; aborts in-flight requests on change and keeps the previous page (dimmed) while loading.
- `src/components/`: `AppShell` (top bar + content column, reusable by other pages), `TopBar` (brand, org search, `RateLimitPill`, `ThemeToggle`), `StartState`, `OrgHeader` (avatar and stat cards), `FilterBar` (+ `SegmentedControl`, `DebouncedInput`, removable filter chips), `RepoTable` (sortable headers, `SkeletonTable`), `Pagination`, `StateView`/`ProblemView` (empty, 404, rate-limited, upstream, invalid cursor), `LanguageDot`, `Avatar`, `OrgChips`.
- `src/styles/tokens.css`: design tokens (colour with `light-dark()`, 4px spacing scale, radius, type scale, 36px control height, focus ring). `src/styles/app.css`: plain CSS organised by area, no framework, system font stack, no network assets.
- `src/theme.ts`: light/dark theme. Defaults to `prefers-color-scheme`; the top bar toggle sets `data-theme` on `<html>` and persists to `localStorage["telescope-theme"]`. An inline script in `index.html` applies it before React mounts (no flash).
- `src/router.ts` + `src/Root.tsx`: pathname router (`/` Explore, `/architecture`) with `history.pushState`/`popstate`; the Explore query string is stashed in `sessionStorage` so switching back restores it. The architecture page is lazy-loaded.
- `src/architecture/`: the `/architecture` page. `content.ts` holds the overview, diagrams (Mermaid sources in `diagrams/*.mmd`), ADRs and roadmap; `mermaid.ts` lazy-loads mermaid and derives its theme from the CSS tokens (re-rendered on theme change); `DiagramCard`/`DiagramViewer` give source, full-screen pan/zoom and SVG download; `Toc` is the scroll-spy contents.
- `src/App.tsx`: wires it together (URL state, states and banners, sorting from column headers).
- `src/test/`: MSW server, typed `openapi-msw` handlers and fixtures, test setup.

## Scripts

`pnpm dev` (proxies `/api` to `VITE_API_PROXY_TARGET`, default `http://localhost:8000`), `pnpm build`, `pnpm test`, `pnpm lint`, `pnpm typecheck`, `pnpm fmt` / `pnpm fmt:check`, `pnpm gen:api` / `pnpm gen:api:check`.

## Client generation

`pnpm gen:api` runs `openapi-typescript ../openapi.json -o src/api/schema.d.ts`. The spec is exported from the FastAPI app; `gen:api:check` fails if the committed types have drifted.

## Testing

Vitest + jsdom + Testing Library. The network is faked with MSW (`setupServer`) using `openapi-msw` handlers typed from `schema.d.ts`, so handlers break at compile time if the contract changes. Tests assert on the query params the handler received and on `window.location.search`. The server starts at setup import time (so fetch is patched before the client captures it); handlers and the URL are reset after each test. Unhandled requests fail the test.
