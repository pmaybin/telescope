from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telescope.main import create_app
from telescope.settings import Settings

T0 = datetime(2030, 3, 17, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.current = T0

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


async def no_sleep(_: float) -> None:
    return None


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def mock() -> respx.MockRouter:
    with respx.mock(assert_all_called=False) as router:
        yield router


ClientFactory = Callable[..., httpx.AsyncClient]


@pytest.fixture
async def make_client(clock: Clock, mock: respx.MockRouter) -> AsyncIterator[ClientFactory]:
    """Builds an ASGI client against a fresh app. GitHub traffic is intercepted by `mock`."""
    opened: list[httpx.AsyncClient] = []
    apps = []

    def factory(token: str | None = None, **settings: object) -> httpx.AsyncClient:
        settings.setdefault("github_max_retries", 1)
        app = create_app(Settings(github_token=token, **settings), sleep=no_sleep, now=clock)  # type: ignore[arg-type]
        apps.append(app)
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        )
        opened.append(client)
        return client

    yield factory
    for client in opened:
        await client.aclose()
    for app in apps:
        await app.state.services.aclose()


@pytest.fixture
def client(make_client: ClientFactory) -> httpx.AsyncClient:
    return make_client()
