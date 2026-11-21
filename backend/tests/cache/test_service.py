from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from telescope.auth.principal import SYSTEM, current_principal
from telescope.cache import CachedSnapshot, InMemorySnapshotStore, Loading, SnapshotService
from telescope.errors import OrgNotFound, UpstreamBudgetExceeded, UpstreamUnavailable
from telescope.models import LoadProgress, Snapshot

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.t = T0

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)


class FakeFetcher:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.calls: list[tuple[str, Snapshot | None]] = []
        self.gate: asyncio.Event | None = None
        self.error: Exception | None = None
        self.progress: LoadProgress | None = None

    async def __call__(
        self, org: str, previous: Snapshot | None, progress: LoadProgress | None = None
    ) -> Snapshot:
        self.calls.append((org, previous))
        self.progress = progress
        if self.gate is not None:
            await self.gate.wait()
        if self.error is not None:
            raise self.error
        return Snapshot(org, (), self.clock.t)


class Spy(InMemorySnapshotStore):
    def __init__(self) -> None:
        super().__init__()
        self.sets = 0

    async def set(self, key: str, snapshot: Snapshot) -> None:
        self.sets += 1
        await super().set(key, snapshot)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def fetcher(clock: Clock) -> FakeFetcher:
    return FakeFetcher(clock)


@pytest.fixture
def store() -> Spy:
    return Spy()


@pytest.fixture
async def service(store: Spy, fetcher: FakeFetcher, clock: Clock):  # type: ignore[no-untyped-def]
    svc = SnapshotService(
        store,
        fetcher,
        ttl_s=100,
        stale_while_revalidate_s=20,
        max_stale_s=1000,
        negative_ttl_s=30,
        now=clock,
    )
    yield svc
    await svc.aclose()


async def test_miss_then_hit(service: SnapshotService, fetcher: FakeFetcher) -> None:
    first = await service.get("Acme")
    second = await service.get("acme")
    assert not first.stale and not second.stale
    assert second.snapshot is first.snapshot
    assert len(fetcher.calls) == 1


async def test_ttl_expiry_refetches_with_previous(
    service: SnapshotService, fetcher: FakeFetcher, clock: Clock
) -> None:
    first = await service.get("acme")
    clock.advance(120)  # beyond ttl + swr
    second = await service.get("acme")
    assert len(fetcher.calls) == 2
    assert fetcher.calls[1][1] is first.snapshot
    assert second.snapshot is not first.snapshot
    assert not second.stale


async def test_swr_returns_immediately_and_refreshes_once(
    service: SnapshotService, fetcher: FakeFetcher, clock: Clock
) -> None:
    first = await service.get("acme")
    clock.advance(110)  # within swr window
    fetcher.gate = asyncio.Event()
    results = [await service.get("acme") for _ in range(3)]
    assert all(r.snapshot is first.snapshot and not r.stale for r in results)
    await asyncio.sleep(0)
    assert len(fetcher.calls) == 2  # one background refresh
    assert fetcher.calls[1][1] is first.snapshot
    fetcher.gate.set()
    await asyncio.gather(*service._background)
    refreshed = await service.get("acme")
    assert refreshed.snapshot is not first.snapshot
    assert len(fetcher.calls) == 2


async def test_swr_background_error_is_logged_not_raised(
    service: SnapshotService,
    fetcher: FakeFetcher,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = await service.get("acme")
    clock.advance(110)
    fetcher.error = UpstreamUnavailable("boom")
    with caplog.at_level(logging.WARNING):
        result = await service.get("acme")
        await asyncio.gather(*service._background)
    assert result.snapshot is first.snapshot
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_concurrent_gets_share_one_fetch(
    service: SnapshotService, fetcher: FakeFetcher
) -> None:
    fetcher.gate = asyncio.Event()
    tasks = [asyncio.ensure_future(service.get("acme")) for _ in range(10)]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    fetcher.gate.set()
    results = await asyncio.gather(*tasks)
    assert len(fetcher.calls) == 1
    assert len({id(r.snapshot) for r in results}) == 1


async def test_concurrent_gets_all_receive_error(
    service: SnapshotService, fetcher: FakeFetcher, store: Spy
) -> None:
    fetcher.gate = asyncio.Event()
    fetcher.error = UpstreamUnavailable("down")
    tasks = [asyncio.ensure_future(service.get("acme")) for _ in range(5)]
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    fetcher.gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert len(fetcher.calls) == 1
    assert all(isinstance(r, UpstreamUnavailable) for r in results)
    assert service._inflight == {}
    # inflight cleaned: a later call fetches again
    fetcher.gate = None
    fetcher.error = None
    await service.get("acme")
    assert len(fetcher.calls) == 2


async def test_expired_upstream_error_serves_stale(
    service: SnapshotService,
    fetcher: FakeFetcher,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first = await service.get("acme")
    clock.advance(500)
    fetcher.error = UpstreamUnavailable("down")
    with caplog.at_level(logging.WARNING):
        result = await service.get("acme")
    assert result.stale and result.snapshot is first.snapshot
    assert any(r.levelno == logging.WARNING for r in caplog.records)


async def test_expired_user_budget_exceeded_serves_stale(
    service: SnapshotService, fetcher: FakeFetcher, clock: Clock
) -> None:
    # A user out of upstream budget still gets the (stale) snapshot rather than a 429.
    first = await service.get("acme")
    clock.advance(500)
    fetcher.error = UpstreamBudgetExceeded("over budget", retry_after=60)
    result = await service.get("acme")
    assert result.stale and result.snapshot is first.snapshot


async def test_beyond_max_stale_raises(
    service: SnapshotService, fetcher: FakeFetcher, clock: Clock
) -> None:
    await service.get("acme")
    clock.advance(1001)
    fetcher.error = UpstreamUnavailable("down")
    with pytest.raises(UpstreamUnavailable):
        await service.get("acme")


async def test_negative_cache(
    service: SnapshotService, fetcher: FakeFetcher, clock: Clock, store: Spy
) -> None:
    fetcher.error = OrgNotFound("ghost")
    with pytest.raises(OrgNotFound):
        await service.get("ghost")
    with pytest.raises(OrgNotFound):
        await service.get("Ghost")
    assert len(fetcher.calls) == 1
    clock.advance(31)
    fetcher.error = None
    await service.get("ghost")
    assert len(fetcher.calls) == 2
    assert store.sets == 1


async def test_org_not_found_on_refresh_deletes_entry(
    service: SnapshotService, fetcher: FakeFetcher, clock: Clock, store: Spy
) -> None:
    await service.get("acme")
    clock.advance(500)
    fetcher.error = OrgNotFound("acme")
    with pytest.raises(OrgNotFound):
        await service.get("acme")
    assert await store.get("acme") is None


async def test_nothing_stored_on_error(
    service: SnapshotService, fetcher: FakeFetcher, store: Spy
) -> None:
    fetcher.error = UpstreamUnavailable("down")
    with pytest.raises(UpstreamUnavailable):
        await service.get("acme")
    fetcher.error = RuntimeError("bug")
    with pytest.raises(RuntimeError):
        await service.get("acme")
    assert store.sets == 0 and len(store) == 0


async def test_lru_eviction(clock: Clock) -> None:
    store = InMemorySnapshotStore(max_entries=2)
    snap = Snapshot("x", (), clock.t)
    await store.set("a", snap)
    await store.set("b", snap)
    await store.get("a")  # a is now most recent
    await store.set("c", snap)
    assert await store.get("b") is None
    assert await store.get("a") is snap and await store.get("c") is snap
    await store.delete("a")
    assert await store.get("a") is None


# ---------------------------------------------------------------- progressive cold load


async def test_progress_is_reported_by_the_fetcher_and_exposed_on_the_flight(
    store: Spy, clock: Clock
) -> None:
    gate = asyncio.Event()

    async def fetcher(
        org: str, previous: Snapshot | None, progress: LoadProgress | None = None
    ) -> Snapshot:
        assert progress is not None
        progress.first_page_landed([], 3)
        await gate.wait()
        progress.page_landed()
        return Snapshot(org, (), clock.t)

    svc = SnapshotService(store, fetcher, cold_wait_s=0, now=clock)
    loading = await svc.get_first_page("acme")
    assert isinstance(loading, Loading)
    await asyncio.sleep(0)
    assert loading.flight.progress.pages_done == 1 and loading.flight.progress.pages_total == 3
    gate.set()
    await asyncio.sleep(0.01)
    assert loading.flight.progress.pages_done == 2
    done = await svc.get_first_page("acme")
    assert isinstance(done, CachedSnapshot)
    await svc.aclose()


async def test_cold_wait_lands_in_time(store: Spy, fetcher: FakeFetcher, clock: Clock) -> None:
    svc = SnapshotService(store, fetcher, cold_wait_s=5, now=clock)  # fetcher is instant
    result = await svc.get_first_page("acme")
    assert isinstance(result, CachedSnapshot) and not result.stale
    await svc.aclose()


async def test_cold_wait_missed_returns_loading_and_the_walk_continues(
    store: Spy, fetcher: FakeFetcher, clock: Clock
) -> None:
    fetcher.gate = asyncio.Event()
    svc = SnapshotService(store, fetcher, cold_wait_s=0, now=clock)
    first = await svc.get_first_page("acme", starter="q1")
    second = await svc.get_first_page("acme", starter="q2")
    assert isinstance(first, Loading) and isinstance(second, Loading)
    assert first.flight is second.flight  # single flight; one walk
    assert first.flight.starter_hash == "q1"
    assert len(fetcher.calls) == 1
    fetcher.gate.set()
    await asyncio.sleep(0.01)
    assert store.sets == 1  # the walk finished and stored despite nobody waiting
    assert isinstance(await svc.get_first_page("acme"), CachedSnapshot)
    await svc.aclose()


async def test_cold_wait_does_not_swallow_walk_errors(
    store: Spy, fetcher: FakeFetcher, clock: Clock
) -> None:
    fetcher.error = UpstreamUnavailable("down")
    svc = SnapshotService(store, fetcher, cold_wait_s=5, now=clock)
    with pytest.raises(UpstreamUnavailable):
        await svc.get_first_page("acme")
    await svc.aclose()


async def test_stale_path_still_blocks_with_cold_wait_enabled(
    store: Spy, fetcher: FakeFetcher, clock: Clock
) -> None:
    svc = SnapshotService(
        store, fetcher, ttl_s=100, stale_while_revalidate_s=20, cold_wait_s=0, now=clock
    )
    await svc.get("acme")
    clock.advance(500)  # beyond ttl + swr
    fetcher.gate = asyncio.Event()
    task = asyncio.ensure_future(svc.get_first_page("acme"))
    await asyncio.sleep(0.01)
    assert not task.done()  # blocks, exactly like get()
    fetcher.gate.set()
    assert isinstance(await task, CachedSnapshot)
    await svc.aclose()


async def test_prewarm_warms_in_the_background_as_system(
    store: Spy, fetcher: FakeFetcher, clock: Clock
) -> None:
    seen = []

    async def spying(
        org: str, previous: Snapshot | None, progress: LoadProgress | None = None
    ) -> Snapshot:
        seen.append(current_principal.get())
        return await fetcher(org, previous, progress)

    svc = SnapshotService(store, spying, now=clock)
    svc.prewarm(["acme", "Globex"])
    await asyncio.gather(*svc._background)
    assert store.sets == 2
    assert seen == [SYSTEM, SYSTEM]
    assert isinstance(await svc.get_first_page("acme"), CachedSnapshot)
    assert len(fetcher.calls) == 2
    await svc.aclose()


async def test_prewarm_failure_is_only_logged(
    store: Spy, fetcher: FakeFetcher, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    fetcher.error = UpstreamUnavailable("down")
    svc = SnapshotService(store, fetcher, now=clock)
    with caplog.at_level(logging.WARNING):
        svc.prewarm(["acme"])
        await asyncio.gather(*svc._background)
    assert "prewarm failed" in caplog.text and store.sets == 0
    await svc.aclose()
