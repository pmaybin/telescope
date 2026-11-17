# Telescope infra

Run from the repo root: `make up` (build and start), `make logs`, `make down`.
Works with no `.env` (tokenless GitHub access, 60 requests/hour) and with one (copy `.env.example`).

| Service | Image / build | Host port | URL |
|---|---|---|---|
| `web` | `../frontend` (nginx, SPA plus `/api/` proxy to `api`) | 8080 | http://localhost:8080 |
| `api` | `../backend` (FastAPI, uvicorn, non-root) | 8000 | http://localhost:8000/docs |
| `lgtm` | `grafana/otel-lgtm:0.41.0` (Grafana, Loki, Tempo, Prometheus, collector) | 3000, 4317 (OTLP gRPC), 4318 (OTLP HTTP) | http://localhost:3000 |
| `redis` | commented-out placeholder under the `redis` profile (stretch bead) | | |

## Dashboard

Open Grafana at http://localhost:3000 (anonymous admin access is on; otherwise `admin`/`admin`).
The **Telescope** dashboard (uid `telescope-overview`) is provisioned from
`grafana/dashboards/telescope.json` via `grafana/provisioning/dashboards.yaml`, and is also the home
dashboard. It has HTTP, cache, GitHub upstream and rate-limit, logs and traces sections.
Panels filter on `service_name="telescope-api"`. Datasource UIDs are `prometheus`, `loki`, `tempo`.
Metrics are exported every 10s, so panels fill in about 20-30s after the first request.

## Token flow

`.env` (`GITHUB_TOKEN`) -> `docker compose --env-file .env` interpolation -> `api` container
environment -> `Settings` in the app. The token is never baked into an image. In production,
a secrets manager (Doppler, 1Password, AWS Secrets Manager) injects the environment variables
instead of a file.

## Port clashes

Host ports can be overridden with `GRAFANA_PORT`, `API_PORT` and `WEB_PORT`
(for example `API_PORT=18000 make up`). Note the Makefile's `down`/`logs` need the same variables.
