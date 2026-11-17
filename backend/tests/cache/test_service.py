from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from telescope.cache import InMemorySnapshotStore, SnapshotService
from telescope.errors import OrgNotFound, UpstreamUnavailable
from telescope.models import Snapshot

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

    async def __call__(self, org: str, previous: Snapshot | None) -> Snapshot:
        self.calls.append((org, previous))
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
