# Codegen and frontend testing research (bead tel-r3)

Versions are from `npm view` on 2026-11-17. Doc claims were fetched from the cited pages. Items marked **(unverified)** come from background knowledge and were not confirmed on a primary page. Check them before relying on them.

| Package | Version | Last published | Engines |
|---|---|---|---|
| openapi-typescript | 7.13.0 | 2026-06-15 | peer typescript ^5.x |
| openapi-fetch | 0.17.0 | 2026-06-15 | - |
| orval | 8.48.0 | 2026-11-14 | node >=22.18 |
| @hey-api/openapi-ts | 0.99.0 (pre-1.0) | 2026-09-30 | node >=22.13 (docs say 22+) |
| msw | 3.0.6 | 2026-11-15 | node >=22.12, ESM-only |
| openapi-msw | 2.1.1 | 2026-10-27 | peer msw ^2.10.5 or ^3 |
| vitest | 5.1.0 | 2026-11-02 | - |
| jsdom / happy-dom | 31.0.1 / 21.0.4 | - | - |
| @testing-library/react | 16.3.3 | - | - |

## 1. Generator comparison

| Criterion | openapi-typescript + openapi-fetch | orval | @hey-api/openapi-ts |
|---|---|---|---|
| OpenAPI 3.1 | Documented: "OpenAPI 3.0 and 3.1", including 3.1 discriminators ([intro](https://openapi-ts.dev/introduction)) | Not confirmed on the pages read | Docs say it "accepts any OpenAPI specification". 3.1 is not stated on the pages read ([get-started](https://heyapi.dev/openapi-ts/get-started)) |
| Generated code | One `.d.ts` of types only, with "no runtime code" | Generates functions per operation (fetch, axios or react-query clients), plus optional mocks | Generates `client.gen.ts`, types and SDK files per plugin |
| Runtime | `openapi-fetch` is about 6 kB ([docs](https://openapi-ts.dev/openapi-fetch/)) | Depends on the client chosen. The generated functions are real code | A small fetch client is generated into your source tree. Size not documented |
| Typed errors | `client.GET()` returns `{data, error, response}`. `error` is typed from the spec's 4xx, 5xx and `default` responses ([docs](https://openapi-ts.dev/openapi-fetch/)). For problem+json, declare the error schema in FastAPI `responses=`. | Typed errors not covered on the page read | Docs claim "type-safe response data and errors". Details not on the page read ([fetch client](https://heyapi.dev/openapi-ts/clients/fetch)) |
| MSW mocking | Handlers are hand-written, or typed with `openapi-msw` against the same `paths` type ([repo](https://github.com/christoph-fricke/openapi-msw)) | Built-in: `mock: { generators: [{ type: 'msw' }] }` emits handlers and faker data ([docs](https://orval.dev/docs/guides/msw)) | A separate plugin is not confirmed. Hand-written handlers work |
| Maintenance | Stable 7.x and 0.17. The last release is June 2026, which is slower but not abandoned | Very active, last published 3 days ago | Active but pre-1.0. The docs advise pinning an exact version |

**Recommendation: `openapi-typescript` + `openapi-fetch`.** The reasons:
- It has the least runtime: about 6 kB and no generated code to review.
- 3.1 support is documented.
- Errors are typed for free via `error`.
- It has a `--check` flag for drift.
- `openapi-msw` gives typed MSW handlers from the same `paths` type.

Orval is the alternative if you want auto-generated mock data. That is more generated code than a 4h timebox for one GET endpoint needs. Hey API is pre-1.0 and its docs ask for exact version pinning.

## 2. Generation command and script

```bash
cd frontend
pnpm add openapi-fetch
pnpm add -D openapi-typescript typescript
```

CLI form is `npx openapi-typescript schema.yaml -o schema.ts` ([CLI docs](https://openapi-ts.dev/cli)). The `--check` flag verifies that generated types are up to date.

```jsonc
// frontend/package.json
"scripts": {
  "gen:api": "openapi-typescript ../openapi.json -o src/api/schema.d.ts",
  "gen:api:check": "openapi-typescript ../openapi.json -o src/api/schema.d.ts --check"
}
```

Output: `frontend/src/api/schema.d.ts`, committed. It exports `paths`, `components` and `operations`.

```ts
// frontend/src/api/client.ts
import createClient from "openapi-fetch";
import type { paths } from "./schema";
export const api = createClient<paths>({ baseUrl: import.meta.env.VITE_API_URL ?? "" });

const { data, error } = await api.GET("/things", { params: { query: { q: "x" } } });
```

The docs recommend `noUncheckedIndexedAccess` in tsconfig and `tsc --noEmit` in CI ([docs](https://openapi-ts.dev/openapi-fetch/)).

## 3. FastAPI side

Deterministic export without a server:

```python
# scripts/export_openapi.py
import json, pathlib
from app.main import app

def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

if __name__ == "__main__":
    pathlib.Path("openapi.json").write_text(render(), encoding="utf-8")
```

Caveats:
- **Optional fields.** On 3.1, Pydantic v2 emits `anyOf: [{type: string}, {type: null}]`. openapi-typescript supports 3.1, so I expect `string | null`. **(unverified)** The CLI page does not describe null handling, so confirm on the real spec.
- **`separate_input_output_schemas`.** It defaults to `True` (added in FastAPI 0.102.0) and emits `Item-Input` and `Item-Output` ([docs](https://fastapi.tiangolo.com/how-to/separate-openapi-schemas/)). In the output schema a field with a default is `required`, because the key is always serialized. In the input schema it is optional. This gives more precise client types, so keep the default. Setting `FastAPI(separate_input_output_schemas=False)` gives one unified schema, where the output field becomes optional.
- **Determinism.** `sort_keys=True` stabilises key order. Pin the fastapi and pydantic versions, because upgrades change the output. Run the export from one place only (CI or a make target).
- **Problem+json errors.** Declare them so they appear in the spec:
  `responses={422: {"model": Problem, "content": {"application/problem+json": {}}}}`. The error type is only as good as what the spec declares. **(unverified)** Check that `error` is typed against the `application/problem+json` content type in the generated types.

## 4. Drift checks (minimal pair)

Backend, pytest:

```python
# tests/test_openapi_drift.py
import pathlib
from scripts.export_openapi import render

def test_openapi_json_is_up_to_date():
    committed = pathlib.Path(__file__).parents[1].joinpath("openapi.json").read_text(encoding="utf-8")
    assert render() == committed, "openapi.json is stale: run `python scripts/export_openapi.py`"
```

Frontend: `pnpm gen:api:check`. It uses the built-in `--check` flag and fails if `schema.d.ts` differs. The fallback is `pnpm gen:api && git diff --exit-code frontend/src/api/schema.d.ts`.

Together these guarantee code -> `openapi.json` -> `schema.d.ts`. Run both in CI.

## 5. Vitest + MSW + React Testing Library

```bash
pnpm add -D vitest jsdom msw openapi-msw @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

```ts
// vitest.config.ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], globals: true },
});
```

```ts
// src/test/setup.ts
import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll } from "vitest";
import { cleanup } from "@testing-library/react";
import { server } from "./server";

beforeAll(() => server.listen({ onUnhandledRequest: "error" })); // msw 3: onUnhandledFrame
afterEach(() => { cleanup(); server.resetHandlers(); });
afterAll(() => server.close());
```

Lifecycle per the [MSW quick start](https://mswjs.io/docs/quick-start): `listen` in `beforeAll`, `resetHandlers` in `afterEach`, `close` in `afterAll`.

```ts
// src/test/server.ts
import { setupServer } from "msw/node";
export const server = setupServer();
```

```ts
// src/test/http.ts, typed handlers
import { createOpenApiHttp } from "openapi-msw";
import type { paths } from "../api/schema";
export const http = createOpenApiHttp<paths>({ baseUrl: "http://localhost:3000" });

// in a test
server.use(http.get("/things", ({ response }) => response(200).json([{ id: 1 }])));
server.use(http.get("/things", ({ response }) =>
  response(422).json({ type: "about:blank", title: "bad", status: 422 }, { headers: { "content-type": "application/problem+json" } })));
```

Plain MSW alternative: `http.get("http://localhost:3000/things", () => HttpResponse.json([...]))`, with `http` and `HttpResponse` from `msw`.

`openapi-msw` 2.1.1 wraps MSW's `http`, so handlers are standard `HttpHandler`s. It types paths, params, query and the `response(status)` helper from the generated `paths`. Its peer range is msw ^2.10.5 or ^3. The README says the lack of frequent releases does not mean it is abandoned ([repo](https://github.com/christoph-fricke/openapi-msw)).

### MSW version note

msw is now at 3.0.6. 3.0 is ESM-only, requires Node >= 22 and TS >= 5.9, and renames `onUnhandledRequest` to `onUnhandledFrame` ([listen docs](https://mswjs.io/docs/api/setup-server/listen)). It also stops managing cookies in Node and stops patching `setTimeout`, so fake timers must be advanced normally. The brief says "MSW v2". Either works with openapi-msw. Prefer 3.x for a new project, or pin `msw@^2` and use `onUnhandledRequest`.

### Gotchas

- Use the global `fetch` (Node 22). Do not add `undici` or `whatwg-fetch` polyfills. MSW intercepts `globalThis.fetch`.
- jsdom has no `fetch`, but Vitest's jsdom env keeps Node's global `fetch`, `Request` and `Response`. **(unverified)**
- A known jsdom problem is a mismatch between jsdom's `AbortSignal` and Node's undici: "Expected signal to be an instance of AbortSignal". **(unverified)** If hit, use `happy-dom` or `// @vitest-environment node` for non-DOM tests.
- Relative URLs do not resolve in Node fetch. Use an absolute `baseUrl` in tests, for example `http://localhost:3000`, and match it in handlers.
- `createClient` may capture `globalThis.fetch` at creation time. **(unverified)** If so, call `server.listen()` before the client module loads (top-level in the setup file), or pass `fetch: (r) => globalThis.fetch(r)`.
- Use `onUnhandledRequest: "error"` so a missing handler fails the test.
- Create a fresh `QueryClient` per test if TanStack Query is used, with `retry: false`.

## Recommendations

1. Use `openapi-typescript` + `openapi-fetch`, with output at `frontend/src/api/schema.d.ts`, committed.
2. Scripts: `gen:api` and `gen:api:check` as above.
3. Export the spec with `scripts/export_openapi.py` (`indent=2`, `sort_keys=True`, trailing newline). Keep the default `separate_input_output_schemas=True`. Declare problem+json responses on the route.
4. Drift pair: the pytest `render() == committed` test, plus `pnpm gen:api:check` in CI.
5. Test stack: Vitest 5 + jsdom + RTL + MSW (3.x, or 2.x pinned) with `setupServer`, and `openapi-msw` for typed handlers. Use an absolute base URL and `onUnhandledRequest: "error"`.
6. First task: generate against the real spec and confirm the Optional (`string | null`) and problem+json error typing. Those two items are the unverified ones.
