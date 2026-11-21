"""Snapshot cache service: TTL, stale-while-revalidate, single-flight, serve-stale-on-error."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from telescope.auth.principal import SYSTEM, Principal, current_principal
from telescope.cache.store import SnapshotStore
from telescope.errors import OrgNotFound, UpstreamBudgetExceeded, UpstreamError
from telescope.models import LoadProgress, Snapshot
from telescope.observability import metrics

logger = logging.getLogger(__name__)

Fetcher = Callable[[str, Snapshot | None, LoadProgress | None], Awaitable[Snapshot]]


@dataclass(frozen=True)
class CachedSnapshot:
    snapshot: Snapshot
    stale: bool


@dataclass(eq=False)
class Flight:
    """One in-flight org walk: its task, observable progress and per-load preview state."""

    key: str
    task: asyncio.Task[Snapshot]
    progress: LoadProgress
    # Who started the walk (charged for it and for its preview); None outside a request.
    initiator: Principal | None
    # Normalised-query hash of the request that started the load (None: system-started).
    starter_hash: str | None
    # Preview results, cached for the life of the flight so polling costs nothing.
    previews: dict[str, asyncio.Task[Any]] = field(default_factory=dict)
    recorded: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Loading:
    """The snapshot is not ready within the cold wait: a provisional response is due."""

    flight: Flight


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
        max_concurrent_walks: int = 2,
        cold_wait_s: float | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._cold_wait = cold_wait_s
        self._store = store
        self._fetcher = fetcher
        self._ttl = ttl_s
        self._swr = stale_while_revalidate_s
        self._max_stale = max_stale_s
        self._negative_ttl = timedelta(seconds=negative_ttl_s)
        self._now = now
        self._walks = asyncio.Semaphore(max(1, max_concurrent_walks))
        self._inflight: dict[str, asyncio.Task[Snapshot]] = {}
        self._flights: dict[str, Flight] = {}
        self._background: set[asyncio.Task[None]] = set()
        self._negative: dict[str, datetime] = {}

    async def get(self, org: str) -> CachedSnapshot:
        result = await self._get(org, wait_s=None, starter=None)
        assert isinstance(result, CachedSnapshot)
        return result

    async def get_first_page(
        self, org: str, *, starter: str | None = None
    ) -> CachedSnapshot | Loading:
        """Like `get`, but on a cold miss waits only `cold_wait_s` for the walk (which keeps
        running regardless) and then returns `Loading` so the caller can answer provisionally.
        `starter` is the normalised-query hash of the caller, recorded when it starts the walk.
        Stale and SWR paths behave exactly as `get`."""
        return await self._get(org, wait_s=self._cold_wait, starter=starter)

    def prewarm(self, orgs: list[str]) -> None:
        """Warm each org in the background as the system principal (never charged to users).
        Failures are only logged."""
        for org in orgs:
            task = asyncio.ensure_future(self._warm(org))
            self._background.add(task)
            task.add_done_callback(self._background.discard)

    async def _warm(self, org: str) -> None:
        key = org.lower()
        try:
            cached = await self._store.get(key)
            if cached is not None and (self._now() - cached.fetched_at).total_seconds() < self._ttl:
                return
            flight, _ = self._flight(key, org, cached, SYSTEM)
            await asyncio.shield(flight.task)
            logger.info("prewarmed org", extra={"org": key})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("prewarm failed", extra={"org": key, "error": type(exc).__name__})

    async def _get(
        self, org: str, *, wait_s: float | None, starter: str | None
    ) -> CachedSnapshot | Loading:
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
            if wait_s is None:
                return CachedSnapshot(await self._refresh(key, org, None), stale=False)
            return await self._cold(key, org, wait_s, starter)

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
        except (UpstreamError, UpstreamBudgetExceeded) as exc:
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

    async def _cold(
        self, key: str, org: str, wait_s: float, starter: str | None
    ) -> CachedSnapshot | Loading:
        for _ in range(2):
            flight, created = self._flight(key, org, None, starter=starter)
            # asyncio.wait never cancels the walk: it keeps running whether or not we wait.
            done, _pending = await asyncio.wait({flight.task}, timeout=max(0.0, wait_s))
            if not done:
                return Loading(flight)
            try:
                return CachedSnapshot(flight.task.result(), stale=False)
            except UpstreamBudgetExceeded:
                if created:
                    raise
                # We joined someone else's walk and it failed on *their* budget: retry with
                # our own (charged to us).
        raise AssertionError("unreachable")  # pragma: no cover

    async def aclose(self) -> None:
        tasks = [*self._background, *self._inflight.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._background.clear()
        self._inflight.clear()
        self._flights.clear()

    # -- internals ---------------------------------------------------------------------

    def _flight(
        self,
        key: str,
        org: str,
        previous: Snapshot | None,
        principal: Principal | None = None,
        *,
        starter: str | None = None,
    ) -> tuple[Flight, bool]:
        """Return the in-flight fetch for `key` (starting one if needed: single-flight) and
        whether this call created it. The task copies the creator's context, so the walk is
        charged to its initiator; joiners create nothing and are never charged."""
        existing = self._flights.get(key)
        if existing is not None:
            return existing, False
        progress = LoadProgress()
        task = asyncio.ensure_future(self._fetch_and_store(key, org, previous, principal, progress))
        flight = Flight(
            key=key,
            task=task,
            progress=progress,
            initiator=principal or current_principal.get(),
            starter_hash=starter,
        )
        self._inflight[key] = task
        self._flights[key] = flight
        task.add_done_callback(lambda t: self._finish(key, t))
        return flight, True

    def _finish(self, key: str, task: asyncio.Task[Snapshot]) -> None:
        if self._inflight.get(key) is task:
            del self._inflight[key]
            self._flights.pop(key, None)
        if not task.cancelled():
            task.exception()  # mark retrieved; waiters/background wrapper handle it

    async def _fetch_and_store(
        self,
        key: str,
        org: str,
        previous: Snapshot | None,
        principal: Principal | None,
        progress: LoadProgress,
    ) -> Snapshot:
        if principal is not None:
            current_principal.set(principal)  # task-local: the task runs in a copied context
        try:
            async with self._walks:
                snapshot = await self._fetcher(org, previous, progress)
        except OrgNotFound:
            await self._store.delete(key)
            self._negative[key] = self._now() + self._negative_ttl
            raise
        await self._store.set(key, snapshot)
        return snapshot

    async def _refresh(self, key: str, org: str, previous: Snapshot | None) -> Snapshot:
        # shield: one cancelled waiter must not cancel the fetch shared by the others.
        flight, created = self._flight(key, org, previous)
        try:
            return await asyncio.shield(flight.task)
        except UpstreamBudgetExceeded:
            if created:
                raise
        # We joined someone else's walk and it failed on *their* budget. Not our problem:
        # start our own (charged to us).
        flight, _ = self._flight(key, org, previous)
        return await asyncio.shield(flight.task)

    def _refresh_in_background(self, key: str, org: str, previous: Snapshot) -> None:
        if key in self._inflight:
            return
        flight, _ = self._flight(key, org, previous, SYSTEM)

        async def watch() -> None:
            try:
                await flight.task
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
