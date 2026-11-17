"""HTTP routes. Business logic lives in the service layer; this module only
binds the contract."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query

from telescope.models import ORG_PATTERN, Problem, RepoPage, RepoQuery

router = APIRouter(prefix="/api")

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
    responses={**PROBLEM_RESPONSES, 304: {"description": "Not modified (If-None-Match)"}},
    summary="List an organisation's public repositories",
    operation_id="listOrgRepos",
)
async def list_org_repos(
    org: Annotated[str, Path(pattern=ORG_PATTERN, description="GitHub organisation login.")],
    query: Annotated[RepoQuery, Query()],
) -> RepoPage:
    # Implemented in bead tel-api.
    raise HTTPException(status_code=501, detail="not implemented")
