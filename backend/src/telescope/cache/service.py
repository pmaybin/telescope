"""Snapshot cache service: TTL, stale-while-revalidate, single-flight, serve-stale-on-error."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from telescope.cache.store import SnapshotStore
from telescope.errors import OrgNotFound, UpstreamError
from telescope.models import Snapshot
from telescope.observability import metrics

logger = logging.getLogger(__name__)

Fetcher = Callable[[str, Snapshot | None], Awaitable[Snapshot]]


@dataclass(frozen=True)
class CachedSnapshot:
    snapshot: Snapshot
    stale: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SnapshotService:
    def __init__(
        self,
        store: SnapshotStore,
        fetcher: Fetcher,
        *,
        ttl_s: float = 600,
        stale_while_revalidate_s: float = 60,
        max_stale_s: float = 86400,
        negative_ttl_s: float = 60,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._fetcher = fetcher
        self._ttl = ttl_s
        self._swr = stale_while_revalidate_s
        self._max_stale = max_stale_s
        self._negative_ttl = timedelta(seconds=negative_ttl_s)
        self._now = now
        self._inflight: dict[str, asyncio.Task[Snapshot]] = {}
        self._background: set[asyncio.Task[None]] = set()
        self._negative: dict[str, datetime] = {}

    async def get(self, org: str) -> CachedSnapshot:
        key = org.lower()

        expires = self._negative.get(key)
        if expires is not None:
            if self._now() < expires:
                metrics.cache_lookup("negative_hit")
                raise OrgNotFound(org)
            del self._negative[key]

        cached = await self._store.get(key)
        if cached is None:
            metrics.cache_lookup("miss")
            return CachedSnapshot(await self._refresh(key, org, None), stale=False)

        age = (self._now() - cached.fetched_at).total_seconds()
        if age < self._ttl:
            metrics.cache_lookup("hit")
            return CachedSnapshot(cached, stale=False)

        if age < self._ttl + self._swr:
            metrics.cache_lookup("hit")
            self._refresh_in_background(key, org, cached)
            return CachedSnapshot(cached, stale=False)

        try:
            fresh = await self._refresh(key, org, cached)
        except UpstreamError as exc:
            age = (self._now() - cached.fetched_at).total_seconds()
            if age < self._max_stale:
                logger.warning(
                    "serving stale snapshot after upstream error",
                    extra={"org": key, "age_s": age, "error": type(exc).__name__},
                )
                metrics.cache_lookup("stale")
                return CachedSnapshot(cached, stale=True)
            raise
        metrics.cache_lookup("miss")
        return CachedSnapshot(fresh, stale=False)

    async def aclose(self) -> None:
        tasks = [*self._background, *self._inflight.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._background.clear()
        self._inflight.clear()

    # -- internals ---------------------------------------------------------------------

    def _flight(self, key: str, org: str, previous: Snapshot | None) -> asyncio.Task[Snapshot]:
        """Return the in-flight fetch for `key`, starting one if needed (single-flight)."""
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.ensure_future(self._fetch_and_store(key, org, previous))
            self._inflight[key] = task
            task.add_done_callback(lambda t: self._finish(key, t))
        return task

    def _finish(self, key: str, task: asyncio.Task[Snapshot]) -> None:
        if self._inflight.get(key) is task:
            del self._inflight[key]
        if not task.cancelled():
            task.exception()  # mark retrieved; waiters/background wrapper handle it

    async def _fetch_and_store(self, key: str, org: str, previous: Snapshot | None) -> Snapshot:
        try:
            snapshot = await self._fetcher(org, previous)
        except OrgNotFound:
            await self._store.delete(key)
            self._negative[key] = self._now() + self._negative_ttl
            raise
        await self._store.set(key, snapshot)
        return snapshot

    async def _refresh(self, key: str, org: str, previous: Snapshot | None) -> Snapshot:
        # shield: one cancelled waiter must not cancel the fetch shared by the others.
        return await asyncio.shield(self._flight(key, org, previous))

    def _refresh_in_background(self, key: str, org: str, previous: Snapshot) -> None:
        if key in self._inflight:
            return
        flight = self._flight(key, org, previous)

        async def watch() -> None:
            try:
                await flight
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "background snapshot refresh failed",
                    extra={"org": key, "error": type(exc).__name__},
                )

        task = asyncio.ensure_future(watch())
        self._background.add(task)
        task.add_done_callback(self._background.discard)
