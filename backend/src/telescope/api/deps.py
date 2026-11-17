"""Service composition: built eagerly in `create_app`, stored on `app.state`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

import httpx
import redis.asyncio as redis
from fastapi import Depends, FastAPI, Request

from telescope.cache import (
    InMemorySnapshotStore,
    RedisSnapshotStore,
    SnapshotService,
    SnapshotStore,
)
from telescope.github import GitHubClient
from telescope.settings import Settings

Sleep = Callable[[float], Awaitable[None]]
Now = Callable[[], datetime]


@dataclass
class Services:
    http: httpx.AsyncClient
    github: GitHubClient
    snapshots: SnapshotService
    redis: redis.Redis | None = None

    async def aclose(self) -> None:
        await self.snapshots.aclose()
        await self.http.aclose()
        if self.redis is not None:
            await self.redis.aclose()


def build_services(
    settings: Settings, *, sleep: Sleep | None = None, now: Now | None = None
) -> Services:
    http = httpx.AsyncClient(timeout=settings.github_timeout_s)
    client_kwargs: dict[str, object] = {}
    cache_kwargs: dict[str, object] = {}
    if sleep is not None:
        client_kwargs["sleep"] = sleep
    if now is not None:
        client_kwargs["now"] = now
        cache_kwargs["now"] = now
    github = GitHubClient(
        http,
        token=settings.github_token,
        base_url=settings.github_api_url,
        max_retries=settings.github_max_retries,
        page_concurrency=settings.github_page_concurrency,
        **client_kwargs,  # type: ignore[arg-type]
    )
    redis_client: redis.Redis | None = None
    store: SnapshotStore
    if settings.cache_backend == "redis":
        redis_client = redis.from_url(settings.redis_url)
        store = RedisSnapshotStore(redis_client)
    else:
        store = InMemorySnapshotStore()
    snapshots = SnapshotService(
        store,
        github.fetch_org_repos,
        ttl_s=settings.cache_ttl_seconds,
        **cache_kwargs,  # type: ignore[arg-type]
    )
    return Services(http=http, github=github, snapshots=snapshots, redis=redis_client)


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


def install_services(app: FastAPI, services: Services) -> None:
    app.state.services = services
