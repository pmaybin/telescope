from __future__ import annotations

import logging
from datetime import timedelta

import httpx
import pytest
import respx

from api.conftest import ClientFactory, Clock
from fixtures.github import BASE, EPOCH, make_repo_json, mock_pages, rl_headers

URL = "/api/orgs/acme/repos"
ORG_URL = f"{BASE}/orgs/acme/repos"


def calls(routes: dict[int, respx.Route]) -> int:
    return sum(r.call_count for r in routes.values())


async def test_happy_path_three_pages_with_filters_and_sort(
    client: httpx.AsyncClient, mock: respx.MockRouter
) -> None:
    routes = mock_pages(mock, 3, last_page_size=50)  # ids 1..250
    r = await client.get(URL, params={"min_stars": 200, "sort": "stars", "limit": 10})

    assert r.status_code == 200
    body = r.json()
    assert body["org"] == "acme"
    assert [i["stars"] for i in body["items"]] == list(range(250, 240, -1))
    assert body["page"]["total"] == 51  # stars 200..250
    assert body["page"]["limit"] == 10
    assert body["page"]["has_next"] is True
    assert body["page"]["has_prev"] is False
    snap = body["snapshot"]
    assert snap["repo_count"] == 250
    assert snap["stale"] is False
    assert snap["cursor_from_older_snapshot"] is False
    assert body["rate_limit"] == {
        "authenticated": False,
        "limit": 5000,
        "remaining": body["rate_limit"]["remaining"],
        "reset_at": "2030-03-17T17:46:40Z",
    }
    assert body["rate_limit"]["remaining"] <= 4000
    assert calls(routes) == 3

    h = r.headers
    assert h["etag"].startswith('W/"')
    assert h["cache-control"] == "private, max-age=60"
    assert h["x-github-ratelimit-limit"] == "5000"
    assert h["x-github-ratelimit-reset"] == str(EPOCH)
    assert "x-request-id" in h


async def test_second_query_with_other_filters_hits_cache(
    client: httpx.AsyncClient, mock: respx.MockRouter
) -> None:
    routes = mock_pages(mock, 3)
    assert (await client.get(URL)).status_code == 200
    assert calls(routes) == 3

    r = await client.get(URL, params={"sort": "name", "order": "asc", "min_stars": 100})
    assert r.status_code == 200
    assert r.json()["page"]["total"] == 201
    assert calls(routes) == 3


async def test_next_cursor_round_trip(client: httpx.AsyncClient, mock: respx.MockRouter) -> None:
    mock_pages(mock, 1, last_page_size=25)
    first = (await client.get(URL, params={"limit": 10})).json()
    second = (
        await client.get(URL, params={"limit": 10, "cursor": first["page"]["next_cursor"]})
    ).json()
    third = (
        await client.get(URL, params={"limit": 10, "cursor": second["page"]["next_cursor"]})
    ).json()

    ids = [i["id"] for p in (first, second, third) for i in p["items"]]
    assert ids == list(range(25, 0, -1))
    assert second["page"]["has_prev"] is True
    assert third["page"]["has_next"] is False
    assert third["page"]["next_cursor"] is None

    back = (
        await client.get(URL, params={"limit": 10, "cursor": third["page"]["prev_cursor"]})
    ).json()
    assert [i["id"] for i in back["items"]] == [i["id"] for i in second["items"]]


async def test_unknown_org_is_404_problem(
    client: httpx.AsyncClient, mock: respx.MockRouter
) -> None:
    mock.get(ORG_URL).mock(return_value=httpx.Response(404, json={"message": "Not Found"}))
    r = await client.get(URL)
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"] == "https://telescope.local/problems/org-not-found"
    assert body["org"] == "acme"
    assert body["instance"] == URL
    assert body["request_id"] == r.headers["x-request-id"]
    assert body["status"] == 404


async def test_primary_rate_limit_is_503_with_retry_after(
    client: httpx.AsyncClient, mock: respx.MockRouter, clock: Clock
) -> None:
    reset = int(clock().timestamp()) + 120
    mock.get(ORG_URL).mock(
        return_value=httpx.Response(
            403, json={"message": "rate limited"}, headers=rl_headers(0, 60, reset)
        )
    )
    r = await client.get(URL)
    assert r.status_code == 503
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"].endswith("/upstream-rate-limited")
    assert body["retry_after"] == 120
    assert r.headers["retry-after"] == "120"
    assert body["rate_limit"]["remaining"] == 0
    assert "x-request-id" in r.headers


async def test_budget_guard_reports_pages_needed(
    client: httpx.AsyncClient, mock: respx.MockRouter, clock: Clock
) -> None:
    reset = int(clock().timestamp()) + 60
    first = mock_pages(mock, 5, remaining=2)
    assert first
    for route in first.values():
        route.mock(
            return_value=httpx.Response(
                200,
                json=[make_repo_json(1)],
                headers={
                    **rl_headers(2, 60, reset),
                    "link": f'<{ORG_URL}?page=5>; rel="last", <{ORG_URL}?page=2>; rel="next"',
                },
            )
        )
    r = await client.get(URL)
    assert r.status_code == 503
    assert r.json()["pages_needed"] == 5
    assert "retry-after" in r.headers


async def test_upstream_500_is_502(client: httpx.AsyncClient, mock: respx.MockRouter) -> None:
    route = mock.get(ORG_URL).mock(return_value=httpx.Response(500))
    r = await client.get(URL)
    assert r.status_code == 502
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["type"].endswith("/upstream-unavailable")
    assert route.call_count == 2  # initial attempt + 1 retry
    assert "x-request-id" in r.headers


async def test_upstream_timeout_is_504(client: httpx.AsyncClient, mock: respx.MockRouter) -> None:
    mock.get(ORG_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    r = await client.get(URL)
    assert r.status_code == 504
    assert r.json()["type"].endswith("/upstream-timeout")


async def test_expired_cache_with_failing_upstream_serves_stale(
    client: httpx.AsyncClient, mock: respx.MockRouter, clock: Clock
) -> None:
    routes = mock_pages(mock, 1, last_page_size=5)
    fresh = await client.get(URL)
    assert fresh.json()["snapshot"]["stale"] is False

    routes[1].mock(return_value=httpx.Response(500))
    clock.advance(10_000)

    r = await client.get(URL)
    assert r.status_code == 200
    assert r.json()["snapshot"]["stale"] is True
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["etag"] != fresh.headers["etag"]
    assert len(r.json()["items"]) == 5


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"sort": "bogus"}, {"min_stars": -1}, {"limit": 101}]
)
async def test_invalid_params_are_422_problem(
    client: httpx.AsyncClient, mock: respx.MockRouter, params: dict[str, object]
) -> None:
    route = mock.get(ORG_URL)
    r = await client.get(URL, params=params)  # type: ignore[arg-type]
    assert r.status_code == 422
    assert r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"].endswith("/validation-error")
    assert body["errors"] and set(body["errors"][0]) == {"loc", "msg", "type"}
    assert "x-request-id" in r.headers
    assert not route.called


async def test_invalid_org_path_is_422(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/orgs/-bad/repos")
    assert r.status_code == 422


async def test_garbage_cursor_is_400(client: httpx.AsyncClient, mock: respx.MockRouter) -> None:
    mock_pages(mock, 1, last_page_size=3)
    r = await client.get(URL, params={"cursor": "not-a-cursor"})
    assert r.status_code == 400
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["type"].endswith("/invalid-cursor")
    assert "x-request-id" in r.headers


async def test_if_none_match_returns_304(client: httpx.AsyncClient, mock: respx.MockRouter) -> None:
    mock_pages(mock, 1, last_page_size=3)
    first = await client.get(URL)
    etag = first.headers["etag"]

    for header in (etag, f'"other", {etag}', "*"):
        r = await client.get(URL, headers={"If-None-Match": header})
        assert r.status_code == 304
        assert r.content == b""
        assert r.headers["etag"] == etag

    other = await client.get(URL, headers={"If-None-Match": 'W/"nope"'})
    assert other.status_code == 200
    changed = await client.get(URL, params={"limit": 1}, headers={"If-None-Match": etag})
    assert changed.status_code == 200


async def test_token_is_sent_upstream_and_never_leaked(
    make_client: ClientFactory, mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "ghp_supersecrettoken1234567890"
    routes = mock_pages(mock, 1, last_page_size=3)
    client = make_client(token=secret)
    with caplog.at_level(logging.DEBUG):
        r = await client.get(URL)
        missing = await client.get("/api/orgs/acme/repos", params={"cursor": "bad"})

    assert r.status_code == 200
    assert missing.status_code == 400
    assert r.json()["rate_limit"]["authenticated"] is True
    sent = routes[1].calls.last.request
    assert sent.headers["authorization"] == f"Bearer {secret}"
    assert secret not in r.text
    assert secret not in str(r.headers)
    assert secret not in caplog.text
    assert secret not in missing.text


async def test_no_token_means_no_authorization_header(
    client: httpx.AsyncClient, mock: respx.MockRouter
) -> None:
    routes = mock_pages(mock, 1, last_page_size=3)
    await client.get(URL)
    assert "authorization" not in routes[1].calls.last.request.headers


async def test_unhandled_error_is_500_problem_without_leaks(
    client: httpx.AsyncClient, mock: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    mock.get(ORG_URL).mock(side_effect=RuntimeError("secret internals"))
    with caplog.at_level(logging.ERROR):
        r = await client.get(URL)
    assert r.status_code == 500
    assert r.headers["content-type"] == "application/problem+json"
    assert r.json()["type"].endswith("/internal-error")
    assert "secret internals" not in r.text
    assert r.json()["request_id"] == r.headers["x-request-id"]
    assert any(rec.exc_info for rec in caplog.records)


async def test_unknown_route_is_problem_json(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/nope")
    assert r.status_code == 404
    assert r.headers["content-type"] == "application/problem+json"
    assert "x-request-id" in r.headers


async def test_client_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/orgs/-bad/repos", headers={"X-Request-ID": "abc-123"})
    assert r.headers["x-request-id"] == "abc-123"
    assert r.json()["request_id"] == "abc-123"


async def test_cors_exposes_headers(client: httpx.AsyncClient, mock: respx.MockRouter) -> None:
    mock_pages(mock, 1, last_page_size=2)
    r = await client.get(URL, headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    exposed = r.headers["access-control-expose-headers"]
    for name in ("X-Request-ID", "ETag", "Retry-After", "X-GitHub-RateLimit-Remaining"):
        assert name in exposed
    pre = await client.options(
        URL,
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert pre.status_code == 400  # only GET is allowed


async def test_ttl_expiry_refetches(
    client: httpx.AsyncClient, mock: respx.MockRouter, clock: Clock
) -> None:
    routes = mock_pages(mock, 1, last_page_size=3)
    await client.get(URL)
    clock.advance(timedelta(minutes=5).total_seconds())
    await client.get(URL)
    assert calls(routes) == 1


async def test_offset_mode_slices_and_reports_offset(
    client: httpx.AsyncClient, mock: respx.MockRouter
) -> None:
    mock_pages(mock, 3, last_page_size=50)  # 250 repos
    r = await client.get(URL, params={"offset": 240, "limit": 20})
    assert r.status_code == 200
    page = r.json()["page"]
    assert [i["stars"] for i in r.json()["items"]] == list(range(10, 0, -1))
    assert page["offset"] == 240
    assert (page["has_prev"], page["has_next"]) == (True, False)
    assert page["next_cursor"] is None and page["prev_cursor"] is None


async def test_offset_changes_etag(client: httpx.AsyncClient, mock: respx.MockRouter) -> None:
    mock_pages(mock, 3)
    a = await client.get(URL, params={"offset": 0, "limit": 10})
    b = await client.get(URL, params={"offset": 10, "limit": 10})
    assert a.headers["etag"] != b.headers["etag"]
    again = await client.get(
        URL, params={"offset": 10, "limit": 10}, headers={"If-None-Match": b.headers["etag"]}
    )
    assert again.status_code == 304


async def test_cursor_plus_offset_is_a_400_problem(
    client: httpx.AsyncClient, mock: respx.MockRouter
) -> None:
    mock_pages(mock, 3)
    first = await client.get(URL, params={"limit": 10})
    cursor = first.json()["page"]["next_cursor"]
    r = await client.get(URL, params={"limit": 10, "cursor": cursor, "offset": 10})
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["type"].endswith("/invalid-pagination")
    assert body["title"] == "Invalid pagination"


async def test_offset_out_of_bounds_is_rejected(
    client: httpx.AsyncClient, mock: respx.MockRouter
) -> None:
    mock_pages(mock, 1)
    assert (await client.get(URL, params={"offset": -1})).status_code == 422
    assert (await client.get(URL, params={"offset": 100_001})).status_code == 422
