from __future__ import annotations

import respx

from fixtures.apps import AppFactory
from fixtures.github import mock_pages

URL = "/api/orgs/acme/repos"


async def token(client, sub: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    r = await client.post("/api/dev/token", json={"sub": sub})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_request_bucket_is_per_principal(
    app_factory: AppFactory, mock: respx.MockRouter, clock
) -> None:  # type: ignore[no-untyped-def]
    mock_pages(mock, 1)
    client = app_factory(user_rate_per_min=60, user_rate_burst=2).client
    alice, bob = await token(client, "alice"), await token(client, "bob")

    assert (await client.get(URL, headers=alice)).status_code == 200
    assert (await client.get(URL, headers=alice)).status_code == 200
    limited = await client.get(URL, headers=alice)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "1"
    body = limited.json()
    assert body["type"].endswith("/client-rate-limited")
    assert body["retry_after"] == 1
    assert limited.headers["content-type"].startswith("application/problem+json")

    assert (await client.get(URL, headers=bob)).status_code == 200  # others unaffected

    clock.advance(1)  # 60/min = 1 token/s
    assert (await client.get(URL, headers=alice)).status_code == 200


async def test_cache_hits_do_not_touch_upstream_budget(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    routes = mock_pages(mock, 2)
    client = app_factory(auth_mode="none", user_upstream_budget=2, user_rate_burst=100).client
    for _ in range(5):
        assert (await client.get(URL)).status_code == 200  # cold walk = 2, then free hits
    assert routes[1].call_count == 1
