from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from fakeredis import FakeAsyncRedis

from telescope.cache import RedisSnapshotStore, SnapshotService
from telescope.models import LoadProgress, Repo, Snapshot

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make_repo(i: int) -> Repo:
    return Repo(
        id=i,
        name=f"r{i}",
        full_name=f"acme/r{i}",
        html_url=f"https://github.com/acme/r{i}",
        description=None,
        language="Python",
        stars=i,
        forks=0,
        open_issues=0,
        archived=False,
        fork=False,
        license=None,
        topics=["a"],
        created_at=T0,
        updated_at=T0,
        pushed_at=None,
    )


def make_snapshot() -> Snapshot:
    return Snapshot("acme", (make_repo(1), make_repo(2)), T0, {1: '"e1"', 2: '"e2"'})


@pytest.fixture
def client() -> FakeAsyncRedis:
    return FakeAsyncRedis()


@pytest.fixture
def store(client: FakeAsyncRedis) -> RedisSnapshotStore:
    return RedisSnapshotStore(client, ttl_s=100)


async def test_round_trip_preserves_equality_id_and_etags(store: RedisSnapshotStore) -> None:
    snap = make_snapshot()
    await store.set("acme", snap)
    got = await store.get("acme")
    assert got == snap
    assert got is not None
    assert got.id == snap.id
    assert got.page_etags == {1: '"e1"', 2: '"e2"'}
    assert got.fetched_at == T0


async def test_miss(store: RedisSnapshotStore) -> None:
    assert await store.get("nope") is None


async def test_delete(store: RedisSnapshotStore) -> None:
    await store.set("acme", make_snapshot())
    await store.delete("acme")
    assert await store.get("acme") is None
    await store.delete("acme")  # idempotent


async def test_ttl_is_set(store: RedisSnapshotStore, client: FakeAsyncRedis) -> None:
    await store.set("acme", make_snapshot())
    ttl = await client.ttl("telescope:snapshot:acme")
    assert 0 < ttl <= 100


async def test_corrupt_payload_is_a_miss(
    store: RedisSnapshotStore, client: FakeAsyncRedis, caplog: pytest.LogCaptureFixture
) -> None:
    await client.set("telescope:snapshot:acme", b"{not json")
    with caplog.at_level(logging.WARNING):
        assert await store.get("acme") is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)

    await client.set("telescope:snapshot:acme", b'{"org": "acme"}')
    assert await store.get("acme") is None


async def test_works_under_snapshot_service(store: RedisSnapshotStore) -> None:
    calls = 0

    async def fetcher(
        org: str, previous: Snapshot | None, progress: LoadProgress | None = None
    ) -> Snapshot:
        nonlocal calls
        calls += 1
        return Snapshot(org, (make_repo(1),), T0)

    service = SnapshotService(store, fetcher, now=lambda: T0)
    first = await service.get("acme")
    second = await service.get("acme")
    assert calls == 1
    assert second.snapshot == first.snapshot
    assert await store.get("acme") == first.snapshot


def test_build_services_selects_backend() -> None:
    from telescope.api.deps import build_services
    from telescope.cache import InMemorySnapshotStore, RedisSnapshotStore
    from telescope.settings import Settings

    mem = build_services(Settings(cache_backend="memory"))
    red = build_services(Settings(cache_backend="redis", redis_url="redis://unused:6379/0"))
    assert isinstance(mem.snapshots._store, InMemorySnapshotStore)
    assert isinstance(red.snapshots._store, RedisSnapshotStore)
    assert red.redis is not None
