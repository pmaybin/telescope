"""Application metrics facade.

Call sites (GitHub client, cache, API) use only these functions, so they don't
depend on OpenTelemetry directly. Backed by the OTel Meter API: with no
MeterProvider configured the global no-op provider makes every call free.

Prometheus names produced via otel-lgtm (contract shared with the dashboard):
  telescope_cache_lookups_total{result="hit|miss|stale|negative_hit"}
  telescope_github_requests_total{status_code="200|304|403|...|error"}
  telescope_github_request_duration_seconds_{bucket,sum,count}{status_code}
  telescope_github_ratelimit_remaining   (gauge, last observed)
  telescope_github_ratelimit_limit       (gauge, last observed)
  telescope_upstream_fetches_total{outcome="full|revalidated|error"}
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from opentelemetry import metrics
from opentelemetry.metrics import CallbackOptions, Counter, Histogram, Observation

CacheResult = Literal["hit", "miss", "stale", "negative_hit"]
FetchOutcome = Literal["full", "revalidated", "error"]


@dataclass
class _Instruments:
    cache_lookups: Counter
    github_requests: Counter
    github_duration: Histogram
    upstream_fetches: Counter


_lock = threading.Lock()
_instruments: _Instruments | None = None
_rate_limit: dict[str, int | None] = {"remaining": None, "limit": None}


def _observe(key: str):  # type: ignore[no-untyped-def]
    def callback(options: CallbackOptions) -> Iterable[Observation]:
        with _lock:
            value = _rate_limit[key]
        if value is not None:
            yield Observation(value)

    return callback


def _get() -> _Instruments:
    global _instruments
    inst = _instruments
    if inst is not None:
        return inst
    with _lock:
        if _instruments is None:
            meter = metrics.get_meter("telescope")
            meter.create_observable_gauge(
                "telescope_github_ratelimit_remaining",
                callbacks=[_observe("remaining")],
                unit="{request}",
                description="Last observed x-ratelimit-remaining",
            )
            meter.create_observable_gauge(
                "telescope_github_ratelimit_limit",
                callbacks=[_observe("limit")],
                unit="{request}",
                description="Last observed x-ratelimit-limit",
            )
            _instruments = _Instruments(
                cache_lookups=meter.create_counter(
                    "telescope_cache_lookups", unit="{lookup}", description="Cache lookups"
                ),
                github_requests=meter.create_counter(
                    "telescope_github_requests", unit="{request}", description="GitHub API calls"
                ),
                github_duration=meter.create_histogram(
                    "telescope_github_request_duration",
                    unit="s",
                    description="GitHub API call duration",
                ),
                upstream_fetches=meter.create_counter(
                    "telescope_upstream_fetches", unit="{fetch}", description="Org fetches"
                ),
            )
        return _instruments


def cache_lookup(result: CacheResult) -> None:
    """Record one cache lookup outcome."""
    _get().cache_lookups.add(1, {"result": result})


def github_request(status_code: int | None, duration_s: float) -> None:
    """Record one upstream HTTP call. `status_code=None` means a network error or timeout."""
    attrs = {"status_code": "error" if status_code is None else str(status_code)}
    inst = _get()
    inst.github_requests.add(1, attrs)
    inst.github_duration.record(duration_s, attrs)


def github_rate_limit(remaining: int | None, limit: int | None) -> None:
    """Record the last observed x-ratelimit-remaining / x-ratelimit-limit."""
    _get()
    with _lock:
        if remaining is not None:
            _rate_limit["remaining"] = remaining
        if limit is not None:
            _rate_limit["limit"] = limit


def upstream_fetch(outcome: FetchOutcome, pages: int) -> None:
    """Record one complete org fetch (all pages) and its outcome."""
    _get().upstream_fetches.add(1, {"outcome": outcome})
