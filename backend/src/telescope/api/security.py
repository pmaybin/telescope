"""Request guards: cross-site check, authentication, per-principal request rate (ADR-0013)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from telescope.api.deps import ServicesDep
from telescope.auth import Principal, current_principal
from telescope.errors import ClientRateLimited, CrossSiteRequest, OrgNotAllowed

# Documents the scheme in OpenAPI (and gives Swagger its Authorize button). `auto_error=False`:
# it never rejects, because whether a bearer is required depends on AUTH_MODE. The
# authenticator below is the only enforcement point.
bearer_scheme = HTTPBearer(
    scheme_name="BearerAuth",
    bearerFormat="JWT",
    description=(
        "Required when `AUTH_MODE` is `dev` (mint one with `POST /api/dev/token`) or `jwt`. "
        "Not used by `tailscale` or `none`."
    ),
    auto_error=False,
)


async def cross_site_guard(request: Request) -> None:
    """Reject browser-initiated cross-site requests (quota burning via a hostile page)."""
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        raise CrossSiteRequest("Cross-site requests to this API are not allowed.")


async def authenticated_principal(
    request: Request,
    services: ServicesDep,
    _credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer_scheme)],
) -> Principal:
    principal = await services.authenticator.authenticate(request)
    # The scope entry feeds the access log and rejection logs; the contextvar feeds the
    # upstream governor (async dependencies run in the endpoint's own task context).
    request.scope["telescope.principal"] = principal
    current_principal.set(principal)

    cfg = services.settings
    decision = await services.limiter.take(
        f"req:{principal.key}", 1, cfg.user_rate_per_min / 60, cfg.user_rate_burst
    )
    if not decision.allowed:
        raise ClientRateLimited("Too many requests; slow down.", retry_after=decision.retry_after)
    return principal


PrincipalDep = Annotated[Principal, Depends(authenticated_principal)]


def check_org_allowed(allowlist: list[str], org: str) -> None:
    """Empty allowlist means every org is allowed."""
    if allowlist and org.lower() not in {o.lower() for o in allowlist}:
        raise OrgNotAllowed(f"Organisation '{org}' is not served by this deployment.")
