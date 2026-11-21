"""App-with-explicit-peer fixture shared by the auth and rate-limit suites."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import httpx
import pytest

from api.conftest import Clock, no_sleep
from telescope.api.deps import Services
from telescope.main import create_app
from telescope.settings import Settings


@dataclass
class AppHandle:
    client: httpx.AsyncClient
    services: Services


AppFactory = Callable[..., AppHandle]


@pytest.fixture
async def app_factory(clock: Clock) -> AsyncIterator[AppFactory]:
    """Builds an app; `peer` is the TCP peer address the app sees. Settings default to
    `AUTH_MODE=dev` with the shipped limits. GitHub traffic is intercepted by `mock`."""
    clients: list[httpx.AsyncClient] = []
    services: list[Services] = []

    def factory(peer: str = "127.0.0.1", **settings: object) -> AppHandle:
        settings.setdefault("github_max_retries", 1)
        settings.setdefault("auth_mode", "dev")
        app = create_app(Settings(**settings), sleep=no_sleep, now=clock)  # type: ignore[arg-type]
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=app, raise_app_exceptions=False, client=(peer, 50000)
            ),
            base_url="http://test",
        )
        clients.append(client)
        services.append(app.state.services)
        return AppHandle(client, app.state.services)

    yield factory
    for c in clients:
        await c.aclose()
    for s in services:
        await s.aclose()
