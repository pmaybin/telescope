import pytest
from fastapi import FastAPI

from telescope.observability import metrics
from telescope.observability.otel import configure_otel, shutdown_otel
from telescope.settings import Settings


def test_configure_otel_noop_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    app = FastAPI()
    assert configure_otel(app, Settings()) is False
    assert not getattr(app, "_is_instrumented_by_opentelemetry", False)
    shutdown_otel()


def test_configure_otel_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert configure_otel(FastAPI(), Settings()) is False


def test_metrics_facade_without_provider() -> None:
    metrics.cache_lookup("hit")
    metrics.github_request(200, 0.1)
    metrics.github_request(None, 0.2)
    metrics.github_rate_limit(10, 5000)
    metrics.github_rate_limit(None, None)
    metrics.upstream_fetch("full", 3)
    for outcome in ("exact", "inexact", "skipped", "disabled", "unavailable", "free"):
        metrics.preview(outcome)  # type: ignore[arg-type]
