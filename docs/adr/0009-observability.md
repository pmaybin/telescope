# ADR-0009: Observability

- Status: Accepted
- Date: 2026-11-17

## Context
The human asked for **dashboard + logs + traces** (decisions log #5). The reviewer should see them with one `make up`. Python OTel status: traces and metrics are stable, **logs are in development** (research `docs/research/otel-lgtm.md` section 3), so the log path must degrade gracefully. Without observability it would be hard to tell cache hits from upstream calls, or to see the rate-limit budget.

## Options considered
**Backend**
- `grafana/otel-lgtm`: one container with Grafana, Prometheus, Tempo, Loki and an OTel collector, and pre-wired datasource links (log -> trace, trace -> logs). Chosen.
- Separate Prometheus/Loki/Tempo/Grafana services: more YAML and more to go wrong, for no benefit.
- Stdout logs only: nothing for Loki to ingest, and no correlation.

**Instrumentation**: the zero-code `opentelemetry-instrument` agent, or programmatic setup. Programmatic is chosen: explicit, testable, a clean no-op, and no fights with uvicorn reload.

**Logging**: structlog (nice API, more bridging to stdlib and uvicorn) or stdlib + `python-json-logger`. The latter is chosen: small, and it adds the OTel `LoggingHandler` beside it.

**Browser OTel**: rejected. It is experimental in places, adds bundle weight and CORS config, and the backend signals already cover the requirement. It is listed as future work.

## Decision
- **Pipeline**: the app exports OTLP/HTTP (`http/protobuf`, port 4318) to `grafana/otel-lgtm:0.41.0`. `configure_otel` is a **no-op** unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set and `OTEL_SDK_DISABLED` is not `true`, so tests and plain local runs install no exporters. It sets up the Resource (`service.name=telescope-api`), tracer and meter providers (metric export every 10s) and a LoggerProvider with the OTel `LoggingHandler`, and instruments FastAPI (excluding `/healthz`) and httpx. `OTEL_SEMCONV_STABILITY_OPT_IN=http` is recommended in Compose (not hard-set in code), which yields stable names such as `http_server_request_duration_seconds_*` with `http_route`.
- **Logs**: JSON to stdout with `timestamp`, `level`, `logger`, `message`, `request_id`, `trace_id`, `span_id` and any `extra`. The same records go to Loki through OTLP (where `service_name` becomes a label, and `trace_id` structured metadata drives the pre-configured Loki -> Tempo link). uvicorn's access log is disabled in favour of one `http.request` line per request. The redaction filter from ADR-0008 applies.
- **Request IDs**: a pure-ASGI middleware accepts a valid incoming `X-Request-ID` (<=128 chars of `[A-Za-z0-9._-]`), or generates a uuid4 hex. It is stored in a ContextVar, echoed in the response, and put in problem bodies (ADR-0006). nginx forwards it.
- **Metrics**: an application facade (`observability/metrics.py`) so call sites never import OTel. Names as seen in Prometheus:
  - `telescope_cache_lookups_total{result="hit|miss|stale|negative_hit"}`
  - `telescope_github_requests_total{status_code}` and `telescope_github_request_duration_seconds_{bucket,sum,count}{status_code}`
  - `telescope_github_ratelimit_remaining` and `telescope_github_ratelimit_limit` (gauges, last observed)
  - `telescope_upstream_fetches_total{outcome="full|revalidated|error"}`
  
  Units are chosen (`{lookup}`, `{request}`, `{fetch}`, `s`) so Prometheus' OTLP translation produces exactly these names.
- **Dashboard** (provisioned JSON, UID `telescope-overview`, 10s refresh, 30m range, datasource UIDs `prometheus`/`loki`/`tempo`): HTTP rate by route/status, p50/p95 latency, 5xx ratio; cache hit ratio and lookups by result; GitHub calls by status, p95 upstream latency, rate-limit remaining vs limit, fetches by outcome; Loki logs and error logs; a Tempo traces table.

## Consequences
- Pro: `make up` gives metrics, logs and traces with working click-through, and cache and quota behaviour are visible at a glance.
- Pro: the facade keeps OTel out of domain code and makes metrics a free no-op in tests.
- Con: OTel Python logs are not stable. Versions are pinned (SDK 1.45.x with contrib 0.66b2), and stdout JSON remains if the OTLP log path breaks.
- Con: metric names depend on Prometheus' OTLP translation, and the semconv opt-in changes the HTTP names. The dashboard targets the opt-in names, and names should be re-verified against `:9090` after a version bump.
- Con: otel-lgtm data is ephemeral (no volume), which is fine for a demo.
- No frontend telemetry: UI errors are visible only through the API's view of them.
