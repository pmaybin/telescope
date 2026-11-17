"""HTTP routes. Business logic lives in the service layer; this module only
binds the contract."""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response

from telescope.api.deps import ServicesDep
from telescope.models import (
    ORG_PATTERN,
    Problem,
    RateLimitState,
    RepoPage,
    RepoQuery,
    SnapshotInfo,
)
from telescope.query import query_hash, run_query

router = APIRouter(prefix="/api")

_STR = {"type": "string"}
_INT = {"type": "integer"}

PROBLEM_RESPONSES: dict[int | str, dict[str, object]] = {
    status: {"model": Problem, "description": desc}
    for status, desc in {
        400: "Invalid cursor or pagination parameters",
        404: "Organisation not found",
        422: "Invalid query parameters",
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
                "ETag": {"description": "Weak validator for this page.", "schema": _STR},
                "Cache-Control": {
                    "description": "`private, max-age=60`, or `no-cache` when stale.",
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
) -> RepoPage | Response:
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


def _etag(snapshot_id: str, query: RepoQuery, stale: bool) -> str:
    raw = "|".join(
        [snapshot_id, query_hash(query), query.cursor or "", str(query.limit), str(stale)]
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
