from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest
import respx
from conftest import Sleeper

from fixtures.github import BASE, EPOCH, make_repo_json, mock_pages, page_response, rl_headers
from telescope.errors import (
    OrgNotFound,
    UpstreamRateLimited,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from telescope.github import GitHubClient

MakeClient = Callable[..., GitHubClient]
URL = f"{BASE}/orgs/acme/repos"


async def test_multi_page_walk_in_order(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    routes = mock_pages(respx_mock, 3, last_page_size=7)
    snap = await make_client(page_concurrency=2).fetch_org_repos("acme")
    assert [r.id for r in snap.repos] == list(range(1, 208))
    assert snap.page_etags == {1: '"etag-1"', 2: '"etag-2"', 3: '"etag-3"'}
    assert all(r.call_count == 1 for r in routes.values())
    first = routes[1].calls[0].request
    assert first.url.params["type"] == "public"
    assert first.url.params["per_page"] == "100"
    assert first.url.params["sort"] == "full_name"


async def test_single_page_without_link(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(URL).mock(
        return_value=httpx.Response(200, json=[make_repo_json(1), make_repo_json(2)])
    )
    snap = await make_client().fetch_org_repos("acme")
    assert len(snap.repos) == 2
    assert len(respx_mock.calls) == 1


async def test_follows_next_when_last_absent(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    nxt = f'<{URL}?page=2>; rel="next"'
    respx_mock.get(URL, params={"page": "1"}).mock(
        return_value=httpx.Response(200, json=[make_repo_json(1)], headers={"link": nxt})
    )
    respx_mock.get(URL, params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=[make_repo_json(2)])
    )
    snap = await make_client().fetch_org_repos("acme")
    assert [r.id for r in snap.repos] == [1, 2]


@pytest.mark.parametrize("token", ["ghp_secret", None])
async def test_authorization_header(
    make_client: MakeClient, respx_mock: respx.MockRouter, token: str | None
) -> None:
    route = respx_mock.get(URL).mock(return_value=httpx.Response(200, json=[]))
    client = make_client(token)
    await client.fetch_org_repos("acme")
    headers = route.calls[0].request.headers
    assert headers.get("authorization") == (f"Bearer {token}" if token else None)
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == "2022-11-28"
    assert headers["user-agent"] == "telescope"
    assert client.rate_limit.authenticated is (token is not None)


async def test_404_is_org_not_found(make_client: MakeClient, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with pytest.raises(OrgNotFound):
        await make_client().fetch_org_repos("acme")
    assert route.call_count == 1


async def test_primary_rate_limit(make_client: MakeClient, respx_mock: respx.MockRouter) -> None:
    respx_mock.get(URL).mock(
        return_value=httpx.Response(403, json={"message": "rate limit"}, headers=rl_headers(0, 60))
    )
    with pytest.raises(UpstreamRateLimited) as exc:
        await make_client().fetch_org_repos("acme")
    assert exc.value.retry_after == 1000
    assert not exc.value.secondary
    assert exc.value.reset_at == datetime.fromtimestamp(EPOCH, UTC)


async def test_secondary_rate_limit_retry_after(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(URL).mock(
        return_value=httpx.Response(
            429, json={"message": "slow down"}, headers={"retry-after": "42", **rl_headers(100)}
        )
    )
    with pytest.raises(UpstreamRateLimited) as exc:
        await make_client().fetch_org_repos("acme")
    assert exc.value.secondary
    assert exc.value.retry_after == 42


async def test_secondary_rate_limit_by_message(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(URL).mock(
        return_value=httpx.Response(403, json={"message": "secondary rate limit"})
    )
    with pytest.raises(UpstreamRateLimited) as exc:
        await make_client().fetch_org_repos("acme")
    assert exc.value.secondary
    assert exc.value.retry_after == 60


async def test_other_403_is_unavailable(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(URL).mock(return_value=httpx.Response(403, json={"message": "Forbidden"}))
    with pytest.raises(UpstreamUnavailable):
        await make_client().fetch_org_repos("acme")


async def test_budget_guard_skips_page_two(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    routes = mock_pages(respx_mock, 5, remaining=2)
    with pytest.raises(UpstreamRateLimited) as exc:
        await make_client().fetch_org_repos("acme")
    assert exc.value.pages_needed == 5
    assert exc.value.retry_after == 1000
    assert routes[1].call_count == 1
    assert routes[2].call_count == 0


async def test_5xx_then_success_with_jittered_sleep(
    make_client: MakeClient, respx_mock: respx.MockRouter, sleeper: Sleeper
) -> None:
    route = respx_mock.get(URL).mock(
        side_effect=[
            httpx.Response(502),
            httpx.Response(503),
            httpx.Response(200, json=[make_repo_json(1)]),
        ]
    )
    snap = await make_client(backoff_base_s=1.0, backoff_max_s=8.0).fetch_org_repos("acme")
    assert len(snap.repos) == 1
    assert route.call_count == 3
    assert len(sleeper.calls) == 2
    assert 0 <= sleeper.calls[0] <= 1.0
    assert 0 <= sleeper.calls[1] <= 2.0
    assert sleeper.calls[0] != sleeper.calls[1]


async def test_5xx_forever(
    make_client: MakeClient, respx_mock: respx.MockRouter, sleeper: Sleeper
) -> None:
    route = respx_mock.get(URL).mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamUnavailable):
        await make_client(max_retries=2).fetch_org_repos("acme")
    assert route.call_count == 3
    assert len(sleeper.calls) == 2


async def test_timeout_forever(
    make_client: MakeClient, respx_mock: respx.MockRouter, sleeper: Sleeper
) -> None:
    route = respx_mock.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamTimeout):
        await make_client(max_retries=2).fetch_org_repos("acme")
    assert route.call_count == 3
    assert len(sleeper.calls) == 2


async def test_network_error_retried_then_unavailable(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(UpstreamUnavailable):
        await make_client(max_retries=1).fetch_org_repos("acme")
    assert route.call_count == 2


async def test_failure_on_page_three_of_five(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    routes = mock_pages(respx_mock, 5)
    routes[3].mock(return_value=httpx.Response(404))
    with pytest.raises(OrgNotFound):
        await make_client(page_concurrency=2).fetch_org_repos("acme")
    assert routes[5].call_count == 0 or routes[3].call_count == 1


async def test_5xx_on_one_page_fails_whole_fetch(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    routes = mock_pages(respx_mock, 5)
    routes[3].mock(return_value=httpx.Response(500))
    with pytest.raises(UpstreamUnavailable):
        await make_client(max_retries=1).fetch_org_repos("acme")


async def test_revalidation_all_304(make_client: MakeClient, respx_mock: respx.MockRouter) -> None:
    mock_pages(respx_mock, 3)
    client = make_client()
    first = await client.fetch_org_repos("acme")
    respx_mock.reset()
    routes = {
        n: respx_mock.get(URL, params={"page": str(n)}).mock(
            return_value=httpx.Response(304, headers=rl_headers(3999))
        )
        for n in (1, 2, 3)
    }
    second = await client.fetch_org_repos("acme", first)
    assert second.id == first.id
    assert second.repos == first.repos
    assert second.page_etags == first.page_etags
    for n, route in routes.items():
        assert route.calls[0].request.headers["if-none-match"] == f'"etag-{n}"'
    assert client.rate_limit.remaining == 3999


async def test_revalidation_one_page_changed(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    mock_pages(respx_mock, 3)
    client = make_client()
    first = await client.fetch_org_repos("acme")
    respx_mock.reset()
    changed = [make_repo_json(100 + i, stargazers_count=999) for i in range(100)]
    link = f'<{URL}?page=3>; rel="last", <{URL}?page=3>; rel="next"'
    respx_mock.get(URL, params={"page": "1"}).mock(
        return_value=httpx.Response(304, headers={"link": link, **rl_headers()})
    )
    respx_mock.get(URL, params={"page": "2"}).mock(
        return_value=httpx.Response(200, json=changed, headers={"etag": '"new-2"', **rl_headers()})
    )
    respx_mock.get(URL, params={"page": "3"}).mock(
        return_value=httpx.Response(304, headers=rl_headers())
    )
    second = await client.fetch_org_repos("acme", first)
    assert second.id != first.id
    assert second.repos[:100] == first.repos[:100]
    assert second.repos[100:200] == tuple(r for r in (await _parse(changed)))
    assert second.repos[200:] == first.repos[200:]
    assert second.page_etags == {1: '"etag-1"', 2: '"new-2"', 3: '"etag-3"'}


async def _parse(raw: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    from telescope.github.mapping import parse_repo

    return [parse_repo(r) for r in raw]  # type: ignore[arg-type]


async def test_revalidation_with_more_pages_fetches_new_ones_plain(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    mock_pages(respx_mock, 2)
    client = make_client()
    first = await client.fetch_org_repos("acme")
    respx_mock.reset()
    routes = mock_pages(respx_mock, 3, etags=True)
    routes[1].mock(
        return_value=httpx.Response(
            304,
            headers={"link": f'<{URL}?page=3>; rel="last"', **rl_headers()},
        )
    )
    routes[2].mock(return_value=httpx.Response(304, headers=rl_headers()))
    second = await client.fetch_org_repos("acme", first)
    assert len(second.repos) == 300
    assert "if-none-match" not in routes[3].calls[0].request.headers
    assert second.id != first.id


async def test_rate_limit_state_updated(
    make_client: MakeClient, respx_mock: respx.MockRouter
) -> None:
    respx_mock.get(URL).mock(
        return_value=httpx.Response(200, json=[], headers=rl_headers(55, 60, EPOCH))
    )
    client = make_client()
    assert client.rate_limit.remaining is None
    await client.fetch_org_repos("acme")
    state = client.rate_limit
    assert (state.limit, state.remaining) == (60, 55)
    assert state.reset_at == datetime.fromtimestamp(EPOCH, UTC)


def test_page_response_helper_has_link() -> None:
    assert 'rel="last"' in page_response(1, 3).headers["link"]
