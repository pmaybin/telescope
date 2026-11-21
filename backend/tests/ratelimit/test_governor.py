from __future__ import annotations

import asyncio

import httpx
import respx

from fixtures.apps import AppFactory, AppHandle
from fixtures.github import BASE, mock_pages, page_response

URL = "/api/orgs/{}/repos"
WINDOW = 100_000  # effectively no refill during a test
MANY = {"user_rate_per_min": 1_000_000, "user_rate_burst": 1_000_000}


async def auth(client: httpx.AsyncClient, sub: str) -> dict[str, str]:
    r = await client.post("/api/dev/token", json={"sub": sub})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def spend_keys(app: AppHandle) -> set[str]:
    return {k for k in app.services.limiter._buckets if k.startswith("spend:")}  # type: ignore[attr-defined]


async def test_random_org_flood_exhausts_one_users_budget_only(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock.get(url__regex=rf"{BASE}/orgs/rand\d+/repos").respond(404)
    mock_pages(mock, 1)  # acme
    app = app_factory(user_upstream_budget=3, user_upstream_window_s=WINDOW, **MANY)
    mallory, alice = await auth(app.client, "mallory"), await auth(app.client, "alice")

    for i in range(3):
        r = await app.client.get(URL.format(f"rand{i}"), headers=mallory)
        assert r.status_code == 404  # each costs one upstream call
    upstream_before = len(mock.calls)

    r = await app.client.get(URL.format("rand99"), headers=mallory)
    assert r.status_code == 429
    assert r.json()["type"].endswith("/upstream-budget-exceeded")
    assert int(r.headers["retry-after"]) >= 1
    assert r.json()["retry_after"] == int(r.headers["retry-after"])
    assert len(mock.calls) == upstream_before  # refused before touching GitHub

    assert (await app.client.get(URL.format("acme"), headers=alice)).status_code == 200
    # Cache hits are free even for the exhausted user.
    assert (await app.client.get(URL.format("acme"), headers=mallory)).status_code == 200


async def test_prefan_out_charge_refuses_unaffordable_walk(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    routes = mock_pages(mock, 5)
    app = app_factory(user_upstream_budget=3, user_upstream_window_s=WINDOW, **MANY)
    headers = await auth(app.client, "alice")

    r = await app.client.get(URL.format("acme"), headers=headers)
    assert r.status_code == 429
    assert r.json()["pages_needed"] == 5
    assert routes[1].call_count == 1  # page 1 only: pages 2-5 were refused up front
    assert sum(routes[n].call_count for n in range(2, 6)) == 0


async def test_joiner_of_inflight_walk_is_not_charged(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    gate = asyncio.Event()
    started = asyncio.Event()

    async def first_page(request: httpx.Request) -> httpx.Response:
        started.set()
        await gate.wait()
        return page_response(1, 3)

    mock.get(f"{BASE}/orgs/acme/repos", params={"page": "1"}).mock(side_effect=first_page)
    for n in (2, 3):
        mock.get(f"{BASE}/orgs/acme/repos", params={"page": str(n)}).mock(
            return_value=page_response(n, 3)
        )
    mock_pages(mock, 3, org="zeta")
    app = app_factory(user_upstream_budget=3, user_upstream_window_s=WINDOW, **MANY)
    alice, bob = await auth(app.client, "alice"), await auth(app.client, "bob")

    initiator = asyncio.create_task(app.client.get(URL.format("acme"), headers=alice))
    await started.wait()
    joiner = asyncio.create_task(app.client.get(URL.format("acme"), headers=bob))
    await asyncio.sleep(0)
    gate.set()
    assert (await initiator).status_code == 200
    assert (await joiner).status_code == 200

    assert spend_keys(app) == {"spend:dev:alice"}  # bob was never charged
    # Bob still has his full budget: an entire 3-page walk is affordable.
    assert (await app.client.get(URL.format("zeta"), headers=bob)).status_code == 200


async def test_joiner_survives_initiators_budget_refusal(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    """If the initiator can't afford the walk, a joiner must not inherit that 429."""
    gate = asyncio.Event()
    started = asyncio.Event()
    state = {"first": True}

    async def page_one(request: httpx.Request) -> httpx.Response:
        if state["first"]:
            state["first"] = False
            started.set()
            await gate.wait()
        return page_response(1, 3)

    mock.get(f"{BASE}/orgs/acme/repos", params={"page": "1"}).mock(side_effect=page_one)
    for n in (2, 3):
        mock.get(f"{BASE}/orgs/acme/repos", params={"page": str(n)}).mock(
            return_value=page_response(n, 3)
        )
    # Budget 3 fits Bob's walk (3 calls) but Alice has already spent 2 elsewhere.
    mock.get(url__regex=rf"{BASE}/orgs/rand\d+/repos").respond(404)
    app = app_factory(user_upstream_budget=3, user_upstream_window_s=WINDOW, **MANY)
    alice, bob = await auth(app.client, "alice"), await auth(app.client, "bob")
    for i in range(2):
        await app.client.get(URL.format(f"rand{i}"), headers=alice)

    initiator = asyncio.create_task(app.client.get(URL.format("acme"), headers=alice))
    await started.wait()
    joiner = asyncio.create_task(app.client.get(URL.format("acme"), headers=bob))
    await asyncio.sleep(0)
    gate.set()
    assert (await initiator).status_code == 429  # page 1 ok, fan-out of 2 > 1 token left
    assert (await joiner).status_code == 200  # Bob re-ran the walk on his own budget


async def test_swr_background_refresh_is_charged_to_system(
    app_factory: AppFactory, mock: respx.MockRouter, clock
) -> None:  # type: ignore[no-untyped-def]
    routes = mock_pages(mock, 1)
    app = app_factory(user_upstream_budget=1, user_upstream_window_s=WINDOW, **MANY)
    alice = await auth(app.client, "alice")
    assert (await app.client.get(URL.format("acme"), headers=alice)).status_code == 200
    assert routes[1].call_count == 1  # Alice's budget (1) is now spent

    clock.advance(600 + 30)  # past TTL, inside the stale-while-revalidate window
    r = await app.client.get(URL.format("acme"), headers=alice)
    assert r.status_code == 200
    await asyncio.gather(*app.services.snapshots._background)

    assert routes[1].call_count == 2  # refreshed despite Alice having no budget left
    assert spend_keys(app) == {"spend:dev:alice"}  # nothing was charged to anyone else


def limited_page(page: int, last: int, *, remaining: int, limit: int = 60) -> httpx.Response:
    response = page_response(page, last, remaining=remaining)
    response.headers["x-ratelimit-limit"] = str(limit)
    return response


async def test_reserve_refuses_users_but_not_system(
    app_factory: AppFactory, mock: respx.MockRouter, clock
) -> None:  # type: ignore[no-untyped-def]
    # limit 60 and reserve fraction 0.2: user spend may not take `remaining` below 12.
    acme = mock.get(f"{BASE}/orgs/acme/repos").mock(return_value=limited_page(1, 1, remaining=30))
    other = mock.get(f"{BASE}/orgs/other/repos").mock(return_value=limited_page(1, 1, remaining=12))
    third = mock.get(f"{BASE}/orgs/third/repos").mock(return_value=limited_page(1, 1, remaining=11))
    app = app_factory(auth_mode="none", upstream_reserve_fraction=0.2, **MANY)

    assert (await app.client.get(URL.format("acme"))).status_code == 200
    assert (await app.client.get(URL.format("other"))).status_code == 200  # 30 - 1 >= 12
    assert app.services.github.rate_limit.remaining == 12

    refused = await app.client.get(URL.format("third"))  # 12 - 1 < 12
    assert refused.status_code == 503
    assert refused.json()["type"].endswith("/upstream-rate-limited")
    assert int(refused.headers["retry-after"]) >= 1
    assert third.call_count == 0  # refused before GitHub was touched

    # The system principal may spend the reserve: SWR refresh of a servable entry.
    clock.advance(600 + 30)
    assert (await app.client.get(URL.format("acme"))).status_code == 200
    await asyncio.gather(*app.services.snapshots._background)
    assert acme.call_count == 2
    assert other.call_count == 1


async def test_reserve_blocks_a_fan_out_that_would_dip_into_it(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    routes = {
        n: mock.get(f"{BASE}/orgs/acme/repos", params={"page": str(n)}).mock(
            return_value=limited_page(n, 5, remaining=14)
        )
        for n in range(1, 6)
    }
    app = app_factory(auth_mode="none", upstream_reserve_fraction=0.2, **MANY)

    r = await app.client.get(URL.format("acme"))  # fan-out of 4 would leave 10 < 12
    assert r.status_code == 503
    assert r.json()["pages_needed"] == 5
    assert routes[1].call_count == 1
    assert sum(routes[n].call_count for n in range(2, 6)) == 0
