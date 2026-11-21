"""Preview calls on the GitHub client: governor charging, reserve, rate-limit isolation."""

from __future__ import annotations

import pytest
import respx

from fixtures.github import BASE, make_repo_json, page_repos, rl_headers
from telescope.auth.principal import Principal, current_principal
from telescope.errors import UpstreamRateLimited
from telescope.github import GitHubClient
from telescope.ratelimit import InMemoryRateLimiter, UpstreamGovernor

ORG_URL = f"{BASE}/orgs/acme/repos"


def governed(make_client, reserve: float) -> GitHubClient:  # type: ignore[no-untyped-def]
    governor = UpstreamGovernor(
        InMemoryRateLimiter(), budget=100, window_s=1000, reserve_fraction=reserve
    )
    return make_client(governor=governor)  # type: ignore[no-any-return]


async def test_list_preview_is_blocked_by_the_core_reserve(
    make_client,
    mock: respx.MockRouter,  # type: ignore[no-untyped-def]
) -> None:
    mock.get(ORG_URL, params={"page": "1"}).respond(
        200, json=page_repos(1, 5), headers=rl_headers(remaining=1200, limit=5000)
    )
    preview = mock.get(ORG_URL, params={"sort": "updated"}).respond(200, json=[])
    client = governed(make_client, reserve=0.2)  # floor 1000; 1200 - 1 is fine
    current_principal.set(Principal("alice", "dev"))
    await client.fetch_org_repos("acme")  # observes remaining=1200
    assert await client.preview_list("acme", sort="updated", direction="desc") == []

    low = governed(make_client, reserve=0.3)  # floor 1500 > 1200 - 1: refused before any call
    mock.get(ORG_URL, params={"page": "1"}).respond(
        200, json=page_repos(1, 5), headers=rl_headers(remaining=1200, limit=5000)
    )
    await low.fetch_org_repos("acme")  # single page: charged before any state is known
    before = preview.call_count
    with pytest.raises(UpstreamRateLimited):
        await low.preview_list("acme", sort="updated", direction="desc")
    assert preview.call_count == before


async def test_search_preview_ignores_core_reserve_but_not_user_budget(
    make_client,
    mock: respx.MockRouter,  # type: ignore[no-untyped-def]
) -> None:
    mock.get(ORG_URL, params={"page": "1"}).respond(
        200, json=page_repos(1, 5), headers=rl_headers(remaining=10, limit=5000)
    )
    search = mock.get(f"{BASE}/search/repositories").respond(
        200,
        json={"total_count": 1, "incomplete_results": False, "items": [make_repo_json(1)]},
        headers={"x-ratelimit-resource": "search", "x-ratelimit-remaining": "9"},
    )
    governor = UpstreamGovernor(
        InMemoryRateLimiter(), budget=2, window_s=100_000, reserve_fraction=0.0
    )
    client = make_client(governor=governor)
    current_principal.set(Principal("alice", "dev"))
    result = await client.preview_search("acme", q="org:acme", order="desc")
    assert result.total_count == 1 and len(result.repos) == 1 and not result.incomplete
    assert client.rate_limit.remaining is None  # Search headers are not core state
    assert search.call_count == 1


async def test_search_response_does_not_overwrite_core_state(
    make_client,
    mock: respx.MockRouter,  # type: ignore[no-untyped-def]
) -> None:
    mock.get(ORG_URL, params={"page": "1"}).respond(
        200, json=page_repos(1, 5), headers=rl_headers(remaining=4000, limit=5000)
    )
    mock.get(f"{BASE}/search/repositories").respond(
        200,
        json={"total_count": 0, "incomplete_results": False, "items": []},
        headers={
            "x-ratelimit-resource": "search",
            "x-ratelimit-limit": "30",
            "x-ratelimit-remaining": "3",
            "x-ratelimit-reset": "1900000000",
        },
    )
    client = make_client()
    await client.fetch_org_repos("acme")
    core = client.rate_limit
    await client.preview_search("acme", q="org:acme", order="desc")
    assert client.rate_limit == core
    assert (core.remaining, core.limit) == (4000, 5000)
