from __future__ import annotations

import random
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from telescope.github import GitHubClient


class Sleeper:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def sleeper() -> Sleeper:
    return Sleeper()


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


@pytest.fixture
def make_client(http: httpx.AsyncClient, sleeper: Sleeper):  # type: ignore[no-untyped-def]
    def factory(token: str | None = None, **kwargs: object) -> GitHubClient:
        return GitHubClient(
            http,
            token=SecretStr(token) if token else None,
            sleep=sleeper,
            rng=random.Random(1234),
            now=lambda: datetime.fromtimestamp(1_900_000_000 - 1000, UTC),
            **kwargs,  # type: ignore[arg-type]
        )

    return factory
