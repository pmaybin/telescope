# OpenTelemetry + grafana/otel-lgtm research (bead tel-r2)

Researched 2026-11-17 from primary sources. Items marked **[unverified]** were not confirmed against running software.

Base for repo files: `https://github.com/grafana/docker-otel-lgtm/blob/main/` (abbreviated `REPO/`).

## 1. grafana/otel-lgtm

- **Version**: latest release `v0.41.0` (published 2026-11-13) (https://github.com/grafana/docker-otel-lgtm/releases). Docker Hub tag `grafana/otel-lgtm:0.41.0` / `:latest`. Pin the tag in compose (assumes Docker Hub tags mirror release names, **[unverified]**). Bundled: Grafana v13.3.1, Prometheus v3.16.0, Tempo v3.1.1, Loki v3.7.10, Pyroscope v2.4.3, OTel Collector v0.165.0 (REPO/docker/Dockerfile).
- **Ports** (`EXPOSE` in REPO/docker/Dockerfile; `-p` list in REPO/run-lgtm.sh):
  - 3000 Grafana
  - 3200 Tempo API
  - 4040 Pyroscope
  - 4317 OTLP gRPC
  - 4318 OTLP HTTP
  - 9090 Prometheus
  - Internal only: Loki 3100, collector health 13133, Tempo OTLP 4418.
- **Auth**: Grafana login `admin` / `admin` (README "View Grafana"). Anonymous auth is also on by default with role Admin: `run-grafana.sh` sets `GF_AUTH_ANONYMOUS_ENABLED=true` and `GF_AUTH_ANONYMOUS_ORG_ROLE=Admin` unless overridden. No login needed in dev.
- **Env vars** (README "Configuration"):
  - `ENABLE_LOGS_{GRAFANA,LOKI,PROMETHEUS,TEMPO,PYROSCOPE,OTELCOL,OBI,ALL}` (container's own logs, default off)
  - `LGTM_SHUTDOWN_TIMEOUT_SECONDS` (default 5)
  - `ENABLE_OBI`, `OBI_TARGET`, `OTEL_EBPF_*` (eBPF; ignore)
  - `{PROMETHEUS,LOKI,TEMPO,PYROSCOPE,OTELCOL}_EXTRA_ARGS`
  - `OTEL_EXPORTER_OTLP_ENDPOINT` / `_HEADERS` / per-signal `_LOGS_/_METRICS_/_TRACES_ENDPOINT`. These make the *collector* forward to a vendor. Do not set them on the lgtm container.
  - any `GF_*` Grafana override, `GF_PLUGINS_PREINSTALL`
  - `LGTM_READY_FILE` (default `/tmp/ready`)
- **Datasource UIDs** (REPO/docker/grafana-datasources.yaml). UIDs are the lowercase strings below:

  | Datasource | uid | internal URL |
  |---|---|---|
  | Prometheus | `prometheus` | http://127.0.0.1:9090 |
  | Tempo | `tempo` | http://127.0.0.1:3200 |
  | Loki | `loki` | http://127.0.0.1:3100 |
  | Pyroscope | `pyroscope` | http://127.0.0.1:4040 |

- **Add our own dashboard JSON** (README "Add custom dashboards"). Provisioning files live in `/otel-lgtm/grafana/conf/provisioning/dashboards/`.

  `dashboards-provisioning.yaml`:
  ```yaml
  apiVersion: 1
  providers:
    - name: "Telescope"
      type: file
      options:
        path: /otel-lgtm/grafana/conf/provisioning/dashboards/custom
        foldersFromFilesStructure: false
  ```
  Compose:
  ```yaml
  lgtm:
    image: grafana/otel-lgtm:0.41.0
    ports: ["3000:3000", "4317:4317", "4318:4318"]
    volumes:
      - ./observability/telescope-dashboard.json:/otel-lgtm/grafana/conf/provisioning/dashboards/custom/telescope-dashboard.json:ro
      - ./observability/dashboards-provisioning.yaml:/otel-lgtm/grafana/conf/provisioning/dashboards/custom.yaml:ro
    environment:
      GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /otel-lgtm/grafana/conf/provisioning/dashboards/custom/telescope-dashboard.json
  ```
  The image's own provider file is `.../provisioning/dashboards/` (grafana-dashboards.yaml, built-in RED and JVM dashboards), so a second `*.yaml` alongside it is additive. Custom config files can also replace `/otel-lgtm/{prometheus,loki-config,tempo-config,otelcol-config}.yaml`.
- **Healthcheck**: `HEALTHCHECK --interval=30s --timeout=5s --retries=3` running `docker/healthcheck.sh`. It requires `/tmp/ready` to exist, then curls Grafana `:3000/api/health`, Loki `:3100/ready`, Tempo `:3200/ready`, Prometheus `:9090/-/ready` and the collector `:13133/ready`. `run-all.sh` polls each service's readiness before writing the ready file. For compose `depends_on`, use `condition: service_healthy`, or just poll `http://localhost:3000/api/health` in scripts.
- **Startup time**: the blog title says "Observability in under 5 seconds" (https://grafana.com/blog/observability-in-under-5-seconds-reflecting-on-a-year-of-grafana-otel-lgtm/). No hard number is in the repo. Expect roughly 5-30s after image pull (**[unverified]**); give the compose healthcheck `start_period: 30s`.
- Data goes to `/data` (ephemeral unless a volume is mounted). The OTLP HTTP receiver has CORS `http://*` allowed (otelcol-config.yaml), which would matter for browser OTel.

## 2. Python OTel for FastAPI + httpx

Latest on PyPI today: `opentelemetry-sdk` / `-exporter-otlp-proto-http` **1.45.2**; contrib instrumentations **0.66b2** (pin as a matched pair; contrib `0.6xb` pairs with sdk `1.4x`).

```
opentelemetry-api==1.45.2
opentelemetry-sdk==1.45.2
opentelemetry-exporter-otlp-proto-http==1.45.2
opentelemetry-instrumentation-fastapi==0.66b2
opentelemetry-instrumentation-httpx==0.66b2
opentelemetry-instrumentation-logging==0.66b2   # optional, see section 3
```

- Use the **HTTP/protobuf exporter** (port 4318): fewer deps than gRPC (no grpcio), and it is the OTel default protocol.
- **Programmatic setup beats `opentelemetry-instrument`** here. It is explicit and testable, we control the no-op logic, and uvicorn `--reload`/workers don't fight the agent. Zero-code docs: https://opentelemetry.io/docs/zero-code/python/ ; FastAPI instrumentor docs: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html
- **Env vars** (standard SDK env spec, https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/):
  - `OTEL_SERVICE_NAME=telescope-api`
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318` (the SDK appends `/v1/traces` etc. for HTTP)
  - `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`
  - `OTEL_SDK_DISABLED=true` (spec-standard kill switch)
  - `OTEL_PYTHON_FASTAPI_EXCLUDED_URLS=healthz,metrics` (avoid tracing health probes)
  - `OTEL_SEMCONV_STABILITY_OPT_IN=http` (see section 4)
  - `OTEL_METRIC_EXPORT_INTERVAL=10000` (ms; default 60000 makes dashboards slow to populate)
- **No-op when unconfigured / in tests**: skip all setup unless an endpoint is present and SDK is not disabled. If no SDK provider is installed, the API's default no-op tracer/meter are used, so `tracer.start_as_current_span` and `meter.create_counter` calls throughout the code stay safe.

```python
# telescope/telemetry.py
import os
from fastapi import FastAPI

def setup_telemetry(app: FastAPI) -> bool:
    if os.getenv("OTEL_SDK_DISABLED", "").lower() == "true":
        return False
    if not (os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")):
        return False                      # tests / local dev without lgtm: nothing installed
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.resources import Resource      # reads OTEL_SERVICE_NAME automatically
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    res = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "telescope-api")})
    tp = TracerProvider(resource=res); tp.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tp)
    metrics.set_meter_provider(MeterProvider(resource=res,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())]))
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
    HTTPXClientInstrumentor().instrument()
    return True
```
Exporters with no args read the endpoint/protocol env vars themselves. In tests, never set the endpoint (and set `OTEL_SDK_DISABLED=true` in `conftest.py`). `set_tracer_provider` may only be called once per process, so the early return also protects test reruns.

## 3. Logs

**Stability**: per opentelemetry.io status table, Python Traces = Stable, Metrics = Stable, **Logs = Development** (https://opentelemetry.io/docs/languages/python/). The SDK module is still the underscored `opentelemetry.sdk._logs` (`LoggerProvider`, `LoggingHandler`; checked on `main`), and the OTLP log exporter is `opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter`. It works, but expect API churn. Pin versions.

Options compared:

| Option | Pros | Cons |
|---|---|---|
| stdlib `logging` + `python-json-logger` | Tiny, stdlib handler model, easy to add OTel `LoggingHandler` next to it | Need a filter to inject trace ids |
| `structlog` | Nicest API, contextvars | One more concept, must bridge to stdlib so uvicorn/httpx logs are formatted and exported too, more wiring |
| `opentelemetry-instrumentation-logging` | Adds `otelTraceID`, `otelSpanID`, `otelServiceName` attributes to every LogRecord (`LoggingInstrumentor().instrument(set_logging_format=True)` or `OTEL_PYTHON_LOG_CORRELATION=true`) | Only injects fields; does not itself output JSON |

Recommended minimal approach: **stdlib logging + python-json-logger + `LoggingInstrumentor` for ids + OTel `LoggingHandler` (OTLP) added only when telemetry is enabled**.

```python
import logging, sys
from pythonjsonlogger.json import JsonFormatter       # python-json-logger >= 3
from opentelemetry.instrumentation.logging import LoggingInstrumentor

def setup_logging(otel_enabled: bool):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(otelTraceID)s %(otelSpanID)s",
        rename_fields={"otelTraceID": "trace_id", "otelSpanID": "span_id"}))
    root = logging.getLogger(); root.handlers[:] = [h]; root.setLevel(logging.INFO)
    if otel_enabled:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        lp = LoggerProvider(resource=res)            # same Resource as traces
        lp.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        set_logger_provider(lp)
        root.addHandler(LoggingHandler(level=logging.INFO, logger_provider=lp))
    LoggingInstrumentor().instrument()               # adds otelTraceID etc. to records (without set_logging_format)
```
Caveats: the injected attributes exist on records even when OTel is off but are empty/`0`, so the format string stays valid. Method name `add_log_record_processor` may have been renamed in newer SDKs **[unverified for 1.45]**; check on install. `LoggingHandler` log records carry the active trace context natively, so Loki gets `trace_id`/`span_id` without the filter. Alternative if the logs SDK proves flaky: drop OTLP logs and rely on stdout JSON only, but then Loki has nothing unless a collector scrapes stdout.

Loki side: otel-lgtm's collector sends logs to Loki's OTLP endpoint (`http://127.0.0.1:3100/otlp`, otelcol-config.yaml), so `service.name` becomes the `service_name` label, and trace/span ids are stored as structured metadata (`trace_id`, `span_id`).

## 4. Metrics and Prometheus names

Prometheus in otel-lgtm ingests via OTLP (`/api/v1/otlp`) and promotes resource attributes `service.name`, `service.instance.id`, `service.namespace`, `deployment.environment*`, etc. to labels (REPO/docker/prometheus.yaml). So every series has `service_name` (promoted), `job` (= `service.name`, or `namespace/name` if service.namespace is set) and `instance` (= `service.instance.id`). Filter dashboards on `service_name="telescope-api"` (stable) or `job=` (what the built-in RED dashboard uses).

Default Prometheus 3 OTLP translation (UnderscoreEscapingWithSuffixes): dots become `_`, unit appended (`ms` -> `_milliseconds`, `s` -> `_seconds`, `By` -> `_bytes`), monotonic counters get `_total`, histograms get `_bucket/_sum/_count`. Reference: https://prometheus.io/docs/guides/opentelemetry/

**FastAPI/ASGI instrumentation depends on `OTEL_SEMCONV_STABILITY_OPT_IN`** (instrumentation `_semconv.py`; the ASGI middleware creates the instruments):

| Mode | Instrument | Prometheus series | Attribute labels |
|---|---|---|---|
| unset (default, old semconv) | `http.server.duration` (ms) | `http_server_duration_milliseconds_{bucket,sum,count}` | `http_method`, `http_status_code`, `http_scheme`, `http_flavor`, `http_host`, `http_target`(or route), `net_host_port` |
| `http` (new semconv) | `http.server.request.duration` (s) | `http_server_request_duration_seconds_{bucket,sum,count}` | `http_request_method`, `http_response_status_code`, `http_route`, `url_scheme`, `network_protocol_version` |
| `http/dup` | both | both | both |

Also in old mode: `http_server_active_requests`, `http_server_request_size_bytes_*`, `http_server_response_size_bytes_*` (labels vary **[unverified]**). httpx client: `http_client_duration_milliseconds_*` (old) / `http_client_request_duration_seconds_*` (new).

The repo's own RED dashboard queries all variants via `{__name__=~"http_server_request_duration_seconds_count|http_server_duration_milliseconds_count|..."}` (REPO/docker/grafana-dashboard-red-metrics-classic.json), confirming both names are expected in the wild.

**Recommendation: set `OTEL_SEMCONV_STABILITY_OPT_IN=http`** so the PromQL uses the stable names and `http_route` (low cardinality, nicer than raw targets), and use seconds. Exact PromQL for the new mode:
```
sum by (http_route) (rate(http_server_request_duration_seconds_count{service_name="telescope-api"}[$__rate_interval]))
histogram_quantile(0.95, sum by (le) (rate(http_server_request_duration_seconds_bucket{service_name="telescope-api"}[$__rate_interval])))
sum(rate(http_server_request_duration_seconds_count{service_name="telescope-api",http_response_status_code=~"5.."}[$__rate_interval]))
```
(Old mode: `http_server_duration_milliseconds_*` and `http_status_code`/`http_method`.)

Custom metrics:
```python
meter = metrics.get_meter("telescope")
cache_hits = meter.create_counter("telescope_cache_hits", unit="1", description="Cache hits")
cache_hits.add(1, {"endpoint": "search"})     # -> telescope_cache_hits_total

def _rl(options):
    yield metrics.Observation(client.remaining, {"upstream": "github"})
meter.create_observable_gauge("telescope_ratelimit_remaining", callbacks=[_rl], unit="1")
```
- Counter becomes `telescope_cache_hits_total`.
- Gauge becomes `telescope_ratelimit_remaining` (Prometheus may add `_ratio` for gauges with unit `1`; **[unverified]**, so use `unit=""` to be safe).
- Verify names once with `curl -s localhost:9090/api/v1/label/__name__/values | tr ',' '\n' | grep telescope`.
- Prometheus Mimir-style label dots become underscores: attribute `cache.name` is label `cache_name`.
- Rate on counters only after the first scrape interval; with 10s export interval use `$__rate_interval` >= 4x.

## 5. Grafana dashboard + log/trace links

Minimal provisioned dashboard JSON (set a fixed `uid`, `id: null`, and reference datasources by uid so no templating is needed):
```json
{
  "id": null, "uid": "telescope-overview", "title": "Telescope", "schemaVersion": 39,
  "version": 1, "refresh": "10s", "time": {"from": "now-30m", "to": "now"}, "tags": ["telescope"],
  "panels": [
    {"id": 1, "type": "timeseries", "title": "Requests/s by route",
     "datasource": {"type": "prometheus", "uid": "prometheus"},
     "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
     "targets": [{"refId": "A", "expr": "sum by (http_route) (rate(http_server_request_duration_seconds_count{service_name=\"telescope-api\"}[$__rate_interval]))", "legendFormat": "{{http_route}}"}]},
    {"id": 2, "type": "logs", "title": "API logs",
     "datasource": {"type": "loki", "uid": "loki"},
     "gridPos": {"x": 0, "y": 8, "w": 24, "h": 10},
     "targets": [{"refId": "A", "expr": "{service_name=\"telescope-api\"}"}],
     "options": {"showTime": true, "enableLogDetails": true, "wrapLogMessage": true}}
  ]
}
```
Loki query examples: `{service_name="telescope-api"} | json | level="ERROR"` (if the body is JSON) and `{service_name="telescope-api"} | trace_id="<id>"` (trace_id is structured metadata with OTLP ingest, so no `| json` needed).

**Trace links are pre-configured** in otel-lgtm (REPO/docker/grafana-datasources.yaml), so no extra work:
- Loki: a derived field `trace_id` (matcherType `label`) links to Tempo (`datasourceUid: tempo`), so a log line with a `trace_id` field shows a "Trace" link.
- Tempo: `tracesToLogsV2` to Loki with query `{service_name=...} | trace_id="<traceId>"`, plus `serviceMap` -> Prometheus and node graph on.
- Prometheus: `exemplarTraceIdDestinations` -> Tempo.

Constraint: `service_name` label must match `service.name`; the log's trace_id arrives only if emitted via OTLP `LoggingHandler` (stdout JSON alone never reaches Loki here).

## 6. Frontend

Browser OTel (web SDK) is not worth it in a 4h exercise: it is experimental in places, adds bundle weight and CORS config (the collector does allow `http://*`), and backend traces/metrics/logs already satisfy the requirement. Skip; mention as future work. A cheap alternative is a `traceparent` passthrough, not needed.

## Sources
- https://github.com/grafana/docker-otel-lgtm (README, docker/Dockerfile, docker/grafana-datasources.yaml, docker/grafana-dashboards.yaml, docker/otelcol-config.yaml, docker/prometheus.yaml, docker/healthcheck.sh, run-lgtm.sh, docker/run-grafana.sh)
- https://opentelemetry.io/docs/languages/python/ (signal status table)
- https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/
- https://github.com/open-telemetry/opentelemetry-python-contrib (instrumentation-fastapi, -asgi, -httpx, -logging, `_semconv.py`)
- https://github.com/open-telemetry/opentelemetry-python (sdk `_logs`)
- https://pypi.org/project/opentelemetry-sdk/ and sibling packages for versions
- https://prometheus.io/docs/guides/opentelemetry/

## Recommendations
1. Image: `grafana/otel-lgtm:0.41.0`, ports 3000/4317/4318, healthcheck-gated `depends_on`.
2. App env: `OTEL_SERVICE_NAME=telescope-api`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318`, `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, `OTEL_SEMCONV_STABILITY_OPT_IN=http`, `OTEL_METRIC_EXPORT_INTERVAL=10000`.
3. Programmatic setup in one `telemetry.py`; no-op unless an endpoint is set and `OTEL_SDK_DISABLED` is not true; never set an endpoint in tests.
4. Logs: stdlib logging + python-json-logger to stdout (trace_id/span_id via `LoggingInstrumentor`), plus the OTel `LoggingHandler` (Development status, pinned) for Loki.
5. Dashboard: mount JSON to `/otel-lgtm/grafana/conf/provisioning/dashboards/custom/` with a provider YAML at `.../dashboards/custom.yaml`; datasource UIDs `prometheus`, `loki`, `tempo`.
6. PromQL on `http_server_request_duration_seconds_*` filtered by `service_name`; custom counter appears as `telescope_cache_hits_total`. Confirm names once against `:9090`.
7. Skip browser OTel.
