"""ADR-0012: provisional first page + progress on a cold load, via the HTTP API."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx

from fixtures.apps import AppFactory, AppHandle
from fixtures.github import BASE, make_repo_json, page_repos, page_response, rl_headers

URL = "/api/orgs/acme/repos"
ORG_URL = f"{BASE}/orgs/acme/repos"
SEARCH_URL = f"{BASE}/search/repositories"
NO_LIMITS = {
    "auth_mode": "none",
    "user_rate_per_min": 1_000_000,
    "user_rate_burst": 1_000_000,
    "user_upstream_budget": 1_000_000,
    "upstream_reserve_fraction": 0.0,
}


@dataclass
class Org:
    """A 3-page org (ids 1..300, stars == id) whose pages 2 and 3 wait on `gate`."""

    gate: asyncio.Event = field(default_factory=asyncio.Event)
    walk: dict[int, respx.Route] = field(default_factory=dict)

    @property
    def walk_calls(self) -> int:
        return sum(r.call_count for r in self.walk.values())


def mock_gated_org(mock: respx.MockRouter, last: int = 3) -> Org:
    org = Org()
    for n in range(1, last + 1):

        async def respond(request: httpx.Request, n: int = n) -> httpx.Response:
            if n > 1:
                await org.gate.wait()
            return page_response(n, last)

        org.walk[n] = mock.get(ORG_URL, params={"page": str(n)}).mock(side_effect=respond)
    return org


def list_preview(
    mock: respx.MockRouter, sort: str, repos: list[dict[str, Any]], **params: str
) -> respx.Route:
    return mock.get(ORG_URL, params={"sort": sort, **params}).mock(
        return_value=httpx.Response(200, json=repos, headers=rl_headers(3999))
    )


def search_preview(
    mock: respx.MockRouter, *, total: int = 300, ids: range = range(300, 200, -1), **extra: Any
) -> respx.Route:
    body = {
        "total_count": total,
        "incomplete_results": False,
        "items": [make_repo_json(i) for i in ids],
    }
    headers = {"x-ratelimit-resource": "search", "x-ratelimit-remaining": "9"}
    return mock.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=body, headers=headers))


async def until(predicate: Callable[[], bool]) -> None:
    for _ in range(400):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


def app(app_factory: AppFactory, **settings: object) -> AppHandle:
    return app_factory(**{**NO_LIMITS, "cold_wait_ms": 0, **settings})


async def poll_until_complete(
    client: httpx.AsyncClient,
    org: Org,
    headers: dict[str, str] | None = None,
    **params: Any,
) -> dict[str, Any]:
    org.gate.set()
    for _ in range(400):
        r = await client.get(URL, params=params, headers=headers)
        body: dict[str, Any] = r.json()
        if body["snapshot"]["complete"]:
            return body
        await asyncio.sleep(0.005)
    raise AssertionError("never completed")


# ------------------------------------------------------------------ shape and cold wait


async def test_provisional_response_shape_headers_and_completion(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    org = mock_gated_org(mock)
    search = search_preview(mock)
    a = app(app_factory)

    r = await a.client.get(URL, params={"sort": "stars", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["snapshot"]["complete"] is False
    assert body["snapshot"]["id"] is None
    assert body["snapshot"]["fetched_at"] is None
    assert body["snapshot"]["repo_count"] is None
    assert body["snapshot"]["progress"]["pages_done"] in (0, 1)
    assert [i["stars"] for i in body["items"]] == [300, 299, 298, 297, 296]
    page = body["page"]
    assert page["total"] == 300  # Search total_count
    assert page["provisional_reason"] is None
    assert not page["has_next"] and not page["has_prev"]
    assert page["next_cursor"] is None and page["prev_cursor"] is None
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["retry-after"] == "1"
    assert "etag" not in r.headers

    await until(lambda: org.walk[1].call_count == 1)
    await until(lambda: a.services.snapshots._flights["acme"].progress.pages_done == 1)
    r = await a.client.get(URL, params={"sort": "stars", "limit": 5})
    assert r.json()["snapshot"]["progress"] == {"pages_done": 1, "pages_total": 3}

    final = await poll_until_complete(a.client, org, sort="stars", limit=5)
    assert final["snapshot"]["id"] and final["snapshot"]["repo_count"] == 300
    assert final["snapshot"]["progress"] is None
    assert final["page"]["total"] == 300 and final["page"]["provisional_reason"] is None
    assert [i["stars"] for i in final["items"]] == [300, 299, 298, 297, 296]
    assert search.call_count == 1  # polling reused the cached preview


async def test_cold_wait_lands_in_time_serves_complete_response(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    org = mock_gated_org(mock)
    org.gate.set()
    search = search_preview(mock)
    a = app_factory(**{**NO_LIMITS, "cold_wait_ms": 5000})

    r = await a.client.get(URL, params={"sort": "stars"})
    body = r.json()
    assert body["snapshot"]["complete"] is True and body["snapshot"]["id"]
    assert r.headers["etag"] and "retry-after" not in r.headers
    assert search.call_count == 0  # the walk won the race: no preview spent


async def test_cursor_and_offset_queries_still_block(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    org = mock_gated_org(mock)
    org.gate.set()
    a = app(app_factory)  # cold_wait_ms=0 would be provisional for a first page
    r = await a.client.get(URL, params={"offset": 30, "limit": 10})
    assert r.json()["snapshot"]["complete"] is True
    assert r.json()["page"]["total"] == 300


async def test_walk_failure_reaches_the_polling_client(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock.get(ORG_URL).respond(404)
    a = app_factory(**{**NO_LIMITS, "cold_wait_ms": 5000})
    r = await a.client.get(URL, params={"sort": "stars"})
    assert r.status_code == 404


# ------------------------------------------------------------------ preview modes


async def test_first_mode_second_query_is_skipped_and_costs_nothing(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    org = mock_gated_org(mock)
    search = search_preview(mock)
    updated = list_preview(mock, "updated", page_repos(1), direction="desc")
    a = app(app_factory, preview_mode="first")

    first = (await a.client.get(URL, params={"sort": "stars"})).json()
    assert first["items"]
    second = (await a.client.get(URL, params={"sort": "updated"})).json()
    assert second["items"] == [] and second["page"]["provisional_reason"] == "preview-skipped"
    for _ in range(3):  # polling both queries is free
        await a.client.get(URL, params={"sort": "stars"})
        await a.client.get(URL, params={"sort": "updated"})
    assert search.call_count == 1 and updated.call_count == 0
    org.gate.set()


async def test_per_query_mode_previews_each_distinct_query_once(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    search = search_preview(mock)
    updated = list_preview(mock, "updated", page_repos(1), direction="desc")
    a = app(app_factory, preview_mode="per-query")

    for _ in range(3):
        stars = (await a.client.get(URL, params={"sort": "stars"})).json()
        upd = (await a.client.get(URL, params={"sort": "updated"})).json()
    assert stars["items"] and upd["items"]
    assert search.call_count == 1 and updated.call_count == 1
    assert dict(updated.calls[0].request.url.params) == {
        "type": "public",
        "sort": "updated",
        "direction": "desc",
        "per_page": "100",
    }


async def test_off_mode_never_calls_upstream_for_previews(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    org = mock_gated_org(mock)
    search = search_preview(mock)
    a = app(app_factory, preview_mode="off")
    body = (await a.client.get(URL, params={"sort": "stars"})).json()
    assert body["items"] == [] and body["page"]["provisional_reason"] == "preview-disabled"
    assert body["snapshot"]["complete"] is False and body["snapshot"]["progress"]
    assert search.call_count == 0
    org.gate.set()


@pytest.mark.parametrize("mode", ["off", "first", "per-query"])
async def test_name_asc_uses_the_walks_own_page_one(
    app_factory: AppFactory, mock: respx.MockRouter, mode: str
) -> None:
    org = mock_gated_org(mock)
    search = search_preview(mock)
    other = list_preview(mock, "full_name", page_repos(1), direction="asc")
    a = app(app_factory, preview_mode=mode)

    await a.client.get(URL, params={"sort": "name"})  # starts the walk; page 1 not here yet
    await until(lambda: a.services.snapshots._flights["acme"].progress.pages_done == 1)
    body = (await a.client.get(URL, params={"sort": "name", "limit": 5})).json()

    assert [i["name"] for i in body["items"]] == [f"repo-{i:04d}" for i in range(1, 6)]
    assert body["snapshot"]["complete"] is False
    assert body["page"]["total"] is None and body["page"]["provisional_reason"] is None
    # Exactly the walk's calls: page 1 (+ pages 2 and 3 waiting on the gate), no preview.
    assert search.call_count == 0 and other.call_count == 0
    assert org.walk[1].call_count == 1
    org.gate.set()


# ------------------------------------------------------------------ search translation


async def test_search_query_translation_and_params(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    search = search_preview(mock)
    a = app(app_factory, preview_mode="per-query")

    await a.client.get(
        URL,
        params={
            "sort": "stars",
            "order": "asc",
            "type": "forks",
            "archived": "false",
            "min_stars": 5,
            "language": "Go",
        },
    )
    await a.client.get(URL, params={"sort": "stars", "type": "sources", "archived": "true"})
    await a.client.get(URL, params={"sort": "stars"})

    qs = [c.request.url.params["q"] for c in search.calls]
    assert qs == [
        'org:acme fork:only archived:false stars:>=5 language:"Go"',
        "org:acme archived:true",  # sources: no fork qualifier (Search excludes forks)
        "org:acme fork:true",
    ]
    first = dict(search.calls[0].request.url.params)
    assert (first["sort"], first["order"], first["per_page"]) == (
        "stars",
        "asc",
        "30",
    )  # per_page = limit
    assert search.calls[1].request.url.params["order"] == "desc"


async def test_language_none_has_no_search_preview(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    search = search_preview(mock)
    a = app(app_factory)
    body = (await a.client.get(URL, params={"sort": "stars", "language": "none"})).json()
    assert body["items"] == [] and body["page"]["provisional_reason"] == "preview-unavailable"
    assert search.call_count == 0


# ------------------------------------------------------------------ exactness


async def test_inexact_when_too_few_matches_and_more_upstream(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    search_preview(mock, total=300)  # 100 items back, only 3 match min_stars>=298
    a = app(app_factory)
    body = (await a.client.get(URL, params={"sort": "stars", "min_stars": 298})).json()
    assert body["items"] == [] and body["page"]["provisional_reason"] == "preview-inexact"


async def test_exact_when_upstream_result_is_complete(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    search_preview(mock, total=3, ids=range(300, 297, -1))  # < 100 items: whole result set
    a = app(app_factory)
    body = (await a.client.get(URL, params={"sort": "stars"})).json()
    assert [i["stars"] for i in body["items"]] == [300, 299, 298]
    assert body["page"]["total"] == 3


async def test_exact_list_preview_filters_locally_and_cuts_to_limit(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    repos = page_repos(1)  # 100 repos, stars 1..100
    list_preview(mock, "pushed", repos, direction="desc")
    a = app(app_factory)
    body = (await a.client.get(URL, params={"sort": "pushed", "min_stars": 50, "limit": 10})).json()
    assert len(body["items"]) == 10  # 51 local matches >= limit
    assert body["page"]["total"] is None


async def test_asc_updated_with_null_sort_key_is_inexact_even_if_complete(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    repos = [make_repo_json(1, updated_at=None), make_repo_json(2)]
    list_preview(mock, "updated", repos, direction="asc")
    a = app(app_factory)
    body = (await a.client.get(URL, params={"sort": "updated", "order": "asc"})).json()
    assert body["items"] == [] and body["page"]["provisional_reason"] == "preview-inexact"


async def test_asc_updated_without_nulls_is_exact(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    list_preview(mock, "updated", [make_repo_json(1), make_repo_json(2)], direction="asc")
    a = app(app_factory)
    body = (await a.client.get(URL, params={"sort": "updated", "order": "asc"})).json()
    assert len(body["items"]) == 2 and body["page"]["provisional_reason"] is None


async def test_desc_updated_with_null_key_is_still_exact(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    list_preview(mock, "updated", [make_repo_json(1, updated_at=None), make_repo_json(2)])
    a = app(app_factory)
    body = (await a.client.get(URL, params={"sort": "updated"})).json()
    assert len(body["items"]) == 2


# ------------------------------------------------------------------ failures


@pytest.mark.parametrize("status", [500, 403, 422])
async def test_preview_failure_is_unavailable_and_walk_still_succeeds(
    app_factory: AppFactory, mock: respx.MockRouter, status: int
) -> None:
    org = mock_gated_org(mock)
    search = mock.get(SEARCH_URL).respond(
        status, headers={"x-ratelimit-resource": "search", "x-ratelimit-remaining": "0"}
    )
    a = app(app_factory)
    r = await a.client.get(URL, params={"sort": "stars"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [] and body["page"]["provisional_reason"] == "preview-unavailable"
    await a.client.get(URL, params={"sort": "stars"})
    assert search.call_count == 1  # failures are cached too: no retry storm while polling

    final = await poll_until_complete(a.client, org, sort="stars")
    assert final["snapshot"]["repo_count"] == 300 and len(final["items"]) == 30


async def test_search_headers_never_touch_core_rate_limit_state(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    org = mock_gated_org(mock)
    search_preview(mock)  # carries x-ratelimit-resource: search, remaining 9
    a = app(app_factory)
    await a.client.get(URL, params={"sort": "stars"})
    await until(lambda: org.walk[1].call_count == 1)
    await until(lambda: a.services.snapshots._flights["acme"].progress.pages_done == 1)
    state = a.services.github.rate_limit
    assert state.remaining == 4000 and state.limit == 5000  # from the core page, not Search
    r = await a.client.get(URL, params={"sort": "stars"})
    assert r.headers["x-github-ratelimit-remaining"] == "4000"
    org.gate.set()


# ------------------------------------------------------------------ governor


async def auth(client: httpx.AsyncClient, sub: str) -> dict[str, str]:
    r = await client.post("/api/dev/token", json={"sub": sub})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def spend(a: AppHandle, key: str) -> float:
    limiter: Any = a.services.limiter
    tokens, _ = limiter._buckets[key]
    return float(tokens)


async def test_preview_is_charged_to_the_initiating_user_only(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_gated_org(mock)
    search_preview(mock)
    a = app_factory(
        auth_mode="dev",
        cold_wait_ms=0,
        user_upstream_budget=10,
        user_upstream_window_s=100_000,
        user_rate_per_min=1_000_000,
        user_rate_burst=1_000_000,
        upstream_reserve_fraction=0.0,
    )
    alice, bob = await auth(a.client, "alice"), await auth(a.client, "bob")

    await a.client.get(URL, params={"sort": "stars"}, headers=alice)
    await until(lambda: a.services.snapshots._flights["acme"].progress.pages_done == 1)
    await a.client.get(URL, params={"sort": "stars"}, headers=bob)  # same query: cached
    limiter: Any = a.services.limiter
    # Alice paid for page 1 + fan-out of 2 pages (3 calls) and the one preview (1 call).
    assert spend(a, "spend:dev:alice") == pytest.approx(10 - 4, abs=0.01)
    assert "spend:dev:bob" not in limiter._buckets


async def test_preview_refused_by_the_governor_degrades_to_unavailable(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    org = mock_gated_org(mock)
    search = search_preview(mock)
    a = app_factory(
        auth_mode="dev",
        cold_wait_ms=0,
        preview_mode="per-query",
        user_upstream_budget=3,  # exactly the 3-page walk: nothing left for a preview
        user_upstream_window_s=100_000,
        user_rate_per_min=1_000_000,
        user_rate_burst=1_000_000,
        upstream_reserve_fraction=0.0,
    )
    alice = await auth(a.client, "alice")
    await a.client.get(URL, params={"sort": "name"}, headers=alice)  # free path; starts the walk
    await until(lambda: a.services.snapshots._flights["acme"].progress.pages_done == 1)
    r = await a.client.get(URL, params={"sort": "stars"}, headers=alice)
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [] and body["page"]["provisional_reason"] == "preview-unavailable"
    assert body["snapshot"]["complete"] is False
    assert search.call_count == 0
    final = await poll_until_complete(a.client, org, sort="name", headers=alice)
    assert final["snapshot"]["repo_count"] == 300  # the walk was unaffected by the refusal
