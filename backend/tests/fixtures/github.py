"""Builders for GitHub API payloads and respx page mocks."""

from __future__ import annotations

from typing import Any

import httpx
import respx

BASE = "https://api.github.com"
EPOCH = 1_900_000_000


def make_repo_json(id: int, name: str | None = None, **overrides: Any) -> dict[str, Any]:
    name = name or f"repo-{id:04d}"
    raw: dict[str, Any] = {
        "id": id,
        "name": name,
        "full_name": f"acme/{name}",
        "html_url": f"https://github.com/acme/{name}",
        "description": f"Repo {name}",
        "language": "Python",
        "stargazers_count": id,
        "forks_count": 1,
        "open_issues_count": 2,
        "archived": False,
        "fork": False,
        "license": {"spdx_id": "MIT", "name": "MIT License"},
        "topics": ["a"],
        "created_at": "2020-01-01T00:00:00Z",
        "updated_at": "2021-01-01T00:00:00Z",
        "pushed_at": "2022-01-01T00:00:00Z",
    }
    raw.update(overrides)
    return raw


def page_repos(page: int, per_page: int = 100) -> list[dict[str, Any]]:
    start = (page - 1) * 100
    return [make_repo_json(start + i + 1) for i in range(per_page)]


def link_header(page: int, last: int, org: str = "acme") -> str | None:
    if last <= 1:
        return None
    url = f"{BASE}/orgs/{org}/repos?type=public&per_page=100"
    parts = []
    if page < last:
        parts.append(f'<{url}&page={page + 1}>; rel="next"')
        parts.append(f'<{url}&page={last}>; rel="last"')
    if page > 1:
        parts.append(f'<{url}&page=1>; rel="first"')
    return ", ".join(parts)


def rl_headers(remaining: int = 4000, limit: int = 5000, reset: int = EPOCH) -> dict[str, str]:
    return {
        "x-ratelimit-limit": str(limit),
        "x-ratelimit-remaining": str(remaining),
        "x-ratelimit-reset": str(reset),
    }


def page_response(
    page: int,
    last: int,
    *,
    per_page: int = 100,
    etag: str | None = None,
    remaining: int = 4000,
    org: str = "acme",
) -> httpx.Response:
    headers = rl_headers(remaining)
    link = link_header(page, last, org)
    if link:
        headers["link"] = link
    if etag:
        headers["etag"] = etag
    return httpx.Response(200, json=page_repos(page, per_page), headers=headers)


def mock_pages(
    router: respx.MockRouter,
    last: int,
    *,
    last_page_size: int = 100,
    org: str = "acme",
    etags: bool = True,
    remaining: int = 4000,
) -> dict[int, respx.Route]:
    """Register one route per page 1..last with correct Link headers."""
    routes: dict[int, respx.Route] = {}
    for n in range(1, last + 1):
        size = last_page_size if n == last else 100
        routes[n] = router.get(f"{BASE}/orgs/{org}/repos", params={"page": str(n)}).mock(
            return_value=page_response(
                n,
                last,
                per_page=size,
                etag=f'"etag-{n}"' if etags else None,
                remaining=remaining,
                org=org,
            )
        )
    return routes
