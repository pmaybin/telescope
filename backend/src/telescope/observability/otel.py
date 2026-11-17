"""OpenTelemetry setup (traces, metrics, logs). A no-op unless an OTLP endpoint is configured.

Recommended env (see docs/research/otel-lgtm.md): OTEL_SEMCONV_STABILITY_OPT_IN=http,
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318, OTEL_SERVICE_NAME=telescope-api.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from telescope.settings import Settings

logger = logging.getLogger(__name__)

_ENDPOINT_VARS = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
)


@dataclass
class _State:
    tracer_provider: Any
    meter_provider: Any
    logger_provider: Any
    log_handler: logging.Handler


_state: _State | None = None


def otel_enabled() -> bool:
    if os.getenv("OTEL_SDK_DISABLED", "").strip().lower() == "true":
        return False
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))


def configure_otel(app: FastAPI, settings: Settings) -> bool:
    """Install providers and instrumentation. Returns False (doing nothing) when disabled."""
    global _state
    if not otel_enabled() or _state is not None:
        return False

    from opentelemetry import metrics, trace
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from telescope.observability.logging import RedactionFilter

    resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "telescope-api")})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10_000)
        ],
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    token = settings.github_token.get_secret_value() if settings.github_token else None
    log_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
    log_handler.addFilter(RedactionFilter(token))
    logging.getLogger().addHandler(log_handler)

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls="/healthz",
    )
    HTTPXClientInstrumentor().instrument(
        tracer_provider=tracer_provider, meter_provider=meter_provider
    )

    _state = _State(tracer_provider, meter_provider, logger_provider, log_handler)
    logger.info("otel.configured", extra={"service_name": resource.attributes["service.name"]})
    return True


def shutdown_otel() -> None:
    """Flush and shut down providers (call from the app lifespan). Safe when never configured."""
    global _state
    if _state is None:
        return
    state, _state = _state, None
    logging.getLogger().removeHandler(state.log_handler)
    state.tracer_provider.shutdown()
    state.meter_provider.shutdown()
    state.logger_provider.shutdown()
