"""Service composition: built eagerly in `create_app`, stored on `app.state`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

import httpx
import redis.asyncio as redis
from fastapi import Depends, FastAPI, Request

from telescope.auth import Authenticator
from telescope.cache import (
    InMemorySnapshotStore,
    RedisSnapshotStore,
    SnapshotService,
    SnapshotStore,
)
from telescope.github import GitHubClient
from telescope.preview import PreviewService
from telescope.ratelimit import (
    InMemoryRateLimiter,
    RateLimiter,
    RedisRateLimiter,
    UpstreamGovernor,
)
from telescope.settings import Settings

Sleep = Callable[[float], Awaitable[None]]
Now = Callable[[], datetime]


@dataclass
class Services:
    http: httpx.AsyncClient
    github: GitHubClient
    snapshots: SnapshotService
    authenticator: Authenticator
    limiter: RateLimiter
    settings: Settings
    preview: PreviewService
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
    redis_client: redis.Redis | None = None
    limiter: RateLimiter
    if settings.cache_backend == "redis":
        redis_client = redis.from_url(settings.redis_url)
        limiter = RedisRateLimiter(redis_client)
    elif now is not None:
        limiter = InMemoryRateLimiter(lambda: now().timestamp())
    else:
        limiter = InMemoryRateLimiter()
    governor = UpstreamGovernor(
        limiter,
        budget=settings.user_upstream_budget,
        window_s=settings.user_upstream_window_s,
        reserve_fraction=settings.upstream_reserve_fraction,
        **({"now": now} if now is not None else {}),
    )
    github = GitHubClient(
        http,
        governor=governor,
        token=settings.github_token,
        base_url=settings.github_api_url,
        max_retries=settings.github_max_retries,
        page_concurrency=settings.github_page_concurrency,
        **client_kwargs,  # type: ignore[arg-type]
    )
    store: SnapshotStore
    if redis_client is not None:
        store = RedisSnapshotStore(redis_client)
    else:
        store = InMemorySnapshotStore()
    snapshots = SnapshotService(
        store,
        github.fetch_org_repos,
        ttl_s=settings.cache_ttl_seconds,
        max_concurrent_walks=settings.max_concurrent_walks,
        cold_wait_s=settings.cold_wait_ms / 1000,
        **cache_kwargs,  # type: ignore[arg-type]
    )
    return Services(
        http=http,
        github=github,
        snapshots=snapshots,
        authenticator=Authenticator(settings, http=http),
        limiter=limiter,
        settings=settings,
        preview=PreviewService(github, mode=settings.preview_mode),
        redis=redis_client,
    )


def get_services(request: Request) -> Services:
    services: Services = request.app.state.services
    return services


ServicesDep = Annotated[Services, Depends(get_services)]


def install_services(app: FastAPI, services: Services) -> None:
    app.state.services = services
