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


class ClientRejection(TelescopeError):
    """The caller (not GitHub) was refused: authentication, policy or a per-user limit.
    `reason` labels the `telescope.client_rejections` metric."""

    reason = "rejected"
    retry_after: int | None = None


class Unauthorized(ClientRejection):
    slug, status, title = "unauthorized", 401, "Authentication required"
    reason = "unauthorized"


class CrossSiteRequest(ClientRejection):
    slug, status, title = "cross-site-request", 403, "Cross-site request refused"
    reason = "cross_site"


class OrgNotAllowed(ClientRejection):
    slug, status, title = "org-not-allowed", 403, "Organisation not allowed"
    reason = "org_not_allowed"


class _Limited(ClientRejection):
    def __init__(self, detail: str, *, retry_after: int) -> None:
        super().__init__(detail)
        self.retry_after = max(1, retry_after)


class ClientRateLimited(_Limited):
    slug, status, title = "client-rate-limited", 429, "Too many requests"
    reason = "rate_limited"


class UpstreamBudgetExceeded(_Limited):
    slug, status, title = "upstream-budget-exceeded", 429, "Upstream request budget exceeded"
    reason = "upstream_budget"

    def __init__(self, detail: str, *, retry_after: int, pages_needed: int | None = None) -> None:
        super().__init__(detail, retry_after=retry_after)
        self.pages_needed = pages_needed
