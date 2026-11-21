"""HTTP routes. Business logic lives in the service layer; this module only
binds the contract."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, Field

from telescope.api.deps import Services, ServicesDep
from telescope.api.problems import problem_response
from telescope.api.security import PrincipalDep, check_org_allowed, cross_site_guard
from telescope.auth.authenticator import DEFAULT_DEV_SUB, DEV_TOKEN_TTL_S
from telescope.cache import Loading
from telescope.models import (
    ORG_PATTERN,
    PageInfo,
    Problem,
    ProgressInfo,
    RateLimitState,
    RepoPage,
    RepoQuery,
    SnapshotInfo,
)
from telescope.query import query_hash, run_query

router = APIRouter(prefix="/api", dependencies=[Depends(cross_site_guard)])

_STR = {"type": "string"}
_INT = {"type": "integer"}

PROBLEM_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": Problem, "description": desc}
    for status, desc in {
        400: "Invalid cursor or pagination parameters",
        401: "Missing or invalid credentials (`WWW-Authenticate: Bearer`)",
        403: "Cross-site request, or organisation not on the allowlist",
        404: "Organisation not found",
        422: "Invalid query parameters",
        429: "Per-client request rate or upstream-call budget exceeded (see Retry-After)",
        502: "GitHub unavailable and no cached data",
        503: "GitHub rate limit exhausted and no cached data (see Retry-After)",
        504: "GitHub timed out and no cached data",
    }.items()
}


@router.get(
    "/orgs/{org}/repos",
    response_model=RepoPage,
    responses={
        200: {
            "description": "A page of repositories.",
            "headers": {
                "ETag": {
                    "description": "Weak validator for this page (absent on provisional pages).",
                    "schema": _STR,
                },
                "Retry-After": {
                    "description": "Seconds to wait before re-requesting; only on provisional "
                    "pages (`snapshot.complete` false).",
                    "schema": _INT,
                },
                "Cache-Control": {
                    "description": "`private, max-age=60`, `no-cache` when stale, or "
                    "`no-store` on provisional pages.",
                    "schema": _STR,
                },
                "X-GitHub-RateLimit-Limit": {
                    "description": "Upstream rate limit ceiling, when known.",
                    "schema": _INT,
                },
                "X-GitHub-RateLimit-Remaining": {
                    "description": "Upstream requests remaining, when known.",
                    "schema": _INT,
                },
                "X-GitHub-RateLimit-Reset": {
                    "description": "Upstream window reset (epoch seconds), when known.",
                    "schema": _INT,
                },
            },
        },
        **PROBLEM_RESPONSES,
        304: {"description": "Not modified (If-None-Match)"},
    },
    summary="List an organisation's public repositories",
    operation_id="listOrgRepos",
)
async def list_org_repos(
    org: Annotated[str, Path(pattern=ORG_PATTERN, description="GitHub organisation login.")],
    query: Annotated[RepoQuery, Query()],
    request: Request,
    response: Response,
    services: ServicesDep,
    _principal: PrincipalDep,
) -> RepoPage | Response:
    check_org_allowed(services.settings.org_allowlist, org)
    first_page = query.cursor is None and not query.offset
    if first_page:
        loaded = await services.snapshots.get_first_page(org, starter=query_hash(query))
        if isinstance(loaded, Loading):
            return await _provisional(org, query, loaded, services, response)
        cached = loaded
    else:
        cached = await services.snapshots.get(org)
    result = run_query(cached.snapshot, query)
    state = services.github.rate_limit

    etag = _etag(cached.snapshot.id, query, cached.stale)
    headers = {
        "ETag": etag,
        "Cache-Control": "no-cache" if cached.stale else "private, max-age=60",
        **_rate_limit_headers(state),
    }
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    response.headers.update(headers)

    return RepoPage(
        org=org,
        items=result.items,
        page=result.page,
        snapshot=SnapshotInfo(
            id=cached.snapshot.id,
            fetched_at=cached.snapshot.fetched_at,
            repo_count=len(cached.snapshot.repos),
            stale=cached.stale,
            cursor_from_older_snapshot=result.cursor_from_older_snapshot,
        ),
        rate_limit=state.to_info(),
    )


async def _provisional(
    org: str, query: RepoQuery, loading: Loading, services: Services, response: Response
) -> RepoPage:
    """Cold load still running: an exact provisional first page when we have one, plus
    progress. Never cacheable; the client re-requests after `Retry-After`."""
    flight = loading.flight
    provisional = await services.preview.provisional(org, query, flight)
    state = services.github.rate_limit
    response.headers.update(
        {"Cache-Control": "no-store", "Retry-After": "1", **_rate_limit_headers(state)}
    )
    return RepoPage(
        org=org,
        items=provisional.items,
        page=PageInfo(
            limit=query.limit,
            total=provisional.total,
            has_next=False,
            has_prev=False,
            next_cursor=None,
            prev_cursor=None,
            offset=query.offset,
            provisional_reason=provisional.reason,
        ),
        snapshot=SnapshotInfo(
            id=None,
            fetched_at=None,
            repo_count=None,
            complete=False,
            progress=ProgressInfo(
                pages_done=flight.progress.pages_done, pages_total=flight.progress.pages_total
            ),
            stale=False,
            cursor_from_older_snapshot=False,
        ),
        rate_limit=state.to_info(),
    )


def _etag(snapshot_id: str, query: RepoQuery, stale: bool) -> str:
    raw = "|".join(
        [
            snapshot_id,
            query_hash(query),
            query.cursor or "",
            str(query.offset),
            str(query.limit),
            str(stale),
        ]
    )
    return f'W/"{hashlib.sha256(raw.encode()).hexdigest()[:16]}"'


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    opaque = etag.removeprefix("W/")
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate == "*" or candidate.removeprefix("W/") == opaque:
            return True
    return False


def _rate_limit_headers(state: RateLimitState) -> dict[str, str]:
    values = {
        "X-GitHub-RateLimit-Limit": state.limit,
        "X-GitHub-RateLimit-Remaining": state.remaining,
        "X-GitHub-RateLimit-Reset": int(state.reset_at.timestamp()) if state.reset_at else None,
    }
    return {k: str(v) for k, v in values.items() if v is not None}


class DevTokenRequest(BaseModel):
    sub: str = Field(default=DEFAULT_DEV_SUB, min_length=1, max_length=64)


class DevToken(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Seconds until the token expires.")


@router.post(
    "/dev/token",
    response_model=DevToken,
    responses={403: PROBLEM_RESPONSES[403], 404: {"description": "Not in dev auth mode"}},
    summary="Mint a short-lived dev JWT (AUTH_MODE=dev only; not a security boundary)",
    operation_id="createDevToken",
)
async def create_dev_token(
    services: ServicesDep, request: Request, body: DevTokenRequest | None = None
) -> DevToken | Response:
    if services.settings.auth_mode != "dev":
        return problem_response(
            request.url.path,
            slug="not-found",
            title="Not Found",
            status=404,
            detail="Dev tokens are only available with AUTH_MODE=dev.",
        )
    sub = body.sub if body else DEFAULT_DEV_SUB
    return DevToken(
        access_token=services.authenticator.mint_dev_token(sub), expires_in=DEV_TOKEN_TTL_S
    )
