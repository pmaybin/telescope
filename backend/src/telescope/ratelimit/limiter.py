"""Token-bucket limiter interface and the in-memory implementation."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after_s: float = 0.0

    @property
    def retry_after(self) -> int:
        """Whole seconds for the `Retry-After` header (at least 1 when refused)."""
        return max(1, math.ceil(self.retry_after_s)) if not self.allowed else 0


class RateLimiter(Protocol):
    """Atomically take `cost` tokens from bucket `key` (capacity `burst`, refilled at
    `rate_per_s`). A refused take consumes nothing. If `cost` exceeds `burst` it can never
    succeed; `retry_after_s` then reports the time to accumulate `cost` tokens."""

    async def take(self, key: str, cost: float, rate_per_s: float, burst: float) -> Decision: ...


def retry_after_for(cost: float, tokens: float, rate_per_s: float) -> float:
    if rate_per_s <= 0:
        return math.inf
    return max(0.0, (cost - tokens) / rate_per_s)


class InMemoryRateLimiter:
    _PRUNE_AT = 10_000

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, updated_at)

    async def take(self, key: str, cost: float, rate_per_s: float, burst: float) -> Decision:
        now = self._clock()
        tokens, updated = self._buckets.get(key, (burst, now))
        tokens = min(burst, tokens + max(0.0, now - updated) * rate_per_s)
        if cost <= tokens:
            self._buckets[key] = (tokens - cost, now)
            self._prune(now, rate_per_s, burst)
            return Decision(True)
        self._buckets[key] = (tokens, now)
        return Decision(False, retry_after_for(cost, tokens, rate_per_s))

    def _prune(self, now: float, rate_per_s: float, burst: float) -> None:
        """Drop buckets that have fully refilled (equivalent to absent) to bound memory."""
        if len(self._buckets) < self._PRUNE_AT or rate_per_s <= 0:
            return
        full_after = burst / rate_per_s
        for key in [k for k, (_, ts) in self._buckets.items() if now - ts >= full_after]:
            del self._buckets[key]
