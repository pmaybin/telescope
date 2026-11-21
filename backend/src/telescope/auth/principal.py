"""Who is making a request (or `system` for background work)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

Source = Literal["jwt", "dev", "tailscale", "ip", "system"]


@dataclass(frozen=True, slots=True)
class Principal:
    sub: str
    source: Source

    @property
    def key(self) -> str:
        """Stable identifier for limiter keys and logs."""
        return f"{self.source}:{self.sub}"


SYSTEM = Principal("system", "system")

# Set by the API dependency for the request; the cache service sets SYSTEM inside background
# refresh tasks. Tasks copy the context at creation, so a walk inherits its initiator.
current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)
