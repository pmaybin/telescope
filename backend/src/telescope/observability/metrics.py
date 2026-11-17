"""Application metrics facade.

Call sites (GitHub client, cache, API) use only these functions, so they don't
depend on OpenTelemetry directly. The functions are no-ops until `configure()` is
called (bead tel-obs implements this with the OTel Meter API).

Prometheus names produced via otel-lgtm (contract shared with the dashboard):
  telescope_cache_lookups_total{result="hit|miss|stale|negative_hit"}
  telescope_github_requests_total{status_code="200|304|403|...|error"}
  telescope_github_request_duration_seconds_{bucket,sum,count}{status_code}
  telescope_github_ratelimit_remaining   (gauge, last observed)
  telescope_github_ratelimit_limit       (gauge, last observed)
  telescope_upstream_fetches_total{outcome="full|revalidated|error"}
"""

from __future__ import annotations

from typing import Literal

CacheResult = Literal["hit", "miss", "stale", "negative_hit"]
FetchOutcome = Literal["full", "revalidated", "error"]


def cache_lookup(result: CacheResult) -> None:
    """Record one cache lookup outcome."""


def github_request(status_code: int | None, duration_s: float) -> None:
    """Record one upstream HTTP call. `status_code=None` means a network error or timeout."""


def github_rate_limit(remaining: int | None, limit: int | None) -> None:
    """Record the last observed x-ratelimit-remaining / x-ratelimit-limit."""


def upstream_fetch(outcome: FetchOutcome, pages: int) -> None:
    """Record one complete org fetch (all pages) and its outcome."""
