"""Domain errors. Raised by the GitHub client, cache and query engine; mapped to
RFC 9457 problem responses in `telescope.api.problems`."""

from __future__ import annotations

from datetime import datetime

from telescope.models import RateLimitState


class TelescopeError(Exception):
    """Base class. `slug`/`status`/`title` drive the problem+json mapping."""

    slug = "internal-error"
    status = 500
    title = "Internal error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail


class OrgNotFound(TelescopeError):
    slug, status, title = "org-not-found", 404, "Organisation not found"

    def __init__(self, org: str) -> None:
        super().__init__(f"GitHub organisation '{org}' does not exist or is not visible.")
        self.org = org


class InvalidCursor(TelescopeError):
    slug, status, title = "invalid-cursor", 400, "Invalid cursor"


class InvalidPagination(TelescopeError):
    slug, status, title = "invalid-pagination", 400, "Invalid pagination"


class UpstreamError(TelescopeError):
    """Any failure talking to GitHub. Never cached; may be masked by serving stale data."""


class UpstreamRateLimited(UpstreamError):
    slug, status, title = "upstream-rate-limited", 503, "GitHub rate limit exhausted"

    def __init__(
        self,
        detail: str,
        *,
        retry_after: int,
        rate_limit: RateLimitState | None = None,
        reset_at: datetime | None = None,
        secondary: bool = False,
        pages_needed: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.retry_after = max(1, retry_after)
        self.rate_limit = rate_limit
        self.reset_at = reset_at
        self.secondary = secondary
        self.pages_needed = pages_needed


class UpstreamUnavailable(UpstreamError):
    slug, status, title = "upstream-unavailable", 502, "GitHub is unavailable"


class UpstreamTimeout(UpstreamError):
    slug, status, title = "upstream-timeout", 504, "GitHub timed out"
