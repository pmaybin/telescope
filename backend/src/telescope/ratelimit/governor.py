"""Upstream-spend governor: protects the shared GitHub quota (ADR-0013 sections 2 and 3)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from telescope.auth.principal import SYSTEM, Principal, current_principal
from telescope.errors import UpstreamBudgetExceeded, UpstreamRateLimited
from telescope.models import RateLimitState
from telescope.observability import metrics
from telescope.ratelimit.limiter import RateLimiter

logger = logging.getLogger(__name__)

_ANONYMOUS = Principal("anonymous", "ip")
_DEFAULT_RETRY_S = 60


class UpstreamGovernor:
    """Consulted by the GitHub client before spending upstream calls.

    The spender is the principal in `current_principal` (the request that initiated the
    walk, or `system` inside background refreshes). `system` is never charged and may use
    the global reserve; everyone else is limited per principal and may not push GitHub's
    `remaining` below `reserve_fraction * limit`.
    """

    def __init__(
        self,
        limiter: RateLimiter,
        *,
        budget: int,
        window_s: float,
        reserve_fraction: float,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._limiter = limiter
        self._budget = budget
        self._rate = budget / window_s
        self._reserve_fraction = reserve_fraction
        self._now = now

    async def charge(
        self, cost: int, state: RateLimitState, *, pages_needed: int | None = None
    ) -> None:
        if cost <= 0:
            return
        principal = current_principal.get() or _ANONYMOUS
        if principal is SYSTEM or principal.source == "system":
            metrics.upstream_spend("system", cost)
            return

        # Reserve first: a refusal here must not consume the user's budget.
        if (
            state.remaining is not None
            and state.limit
            and state.remaining - cost < self._reserve_fraction * state.limit
        ):
            raise UpstreamRateLimited(
                "Remaining GitHub quota is reserved for background refreshes.",
                retry_after=self._seconds_until(state.reset_at),
                rate_limit=state,
                reset_at=state.reset_at,
                pages_needed=pages_needed,
            )

        decision = await self._limiter.take(
            f"spend:{principal.key}", cost, self._rate, self._budget
        )
        if not decision.allowed:
            raise UpstreamBudgetExceeded(
                f"Upstream request budget of {self._budget} calls per "
                f"{round(self._budget / self._rate)} s exhausted.",
                retry_after=decision.retry_after,
                pages_needed=pages_needed,
            )
        metrics.upstream_spend("user", cost)

    def _seconds_until(self, reset_at: datetime | None) -> int:
        if reset_at is None:
            return _DEFAULT_RETRY_S
        return max(1, int((reset_at - self._now()).total_seconds()))
