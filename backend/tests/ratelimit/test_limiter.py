from __future__ import annotations

import fakeredis
import pytest

from telescope.ratelimit import InMemoryRateLimiter, RedisRateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def test_burst_then_refusal_then_refill() -> None:
    clock = FakeClock()
    rl = InMemoryRateLimiter(clock)
    for _ in range(3):
        assert (await rl.take("k", 1, rate_per_s=2, burst=3)).allowed
    refused = await rl.take("k", 1, rate_per_s=2, burst=3)
    assert not refused.allowed
    assert refused.retry_after_s == pytest.approx(0.5)
    assert refused.retry_after == 1

    clock.t += 0.5  # one token refilled
    assert (await rl.take("k", 1, 2, 3)).allowed
    assert not (await rl.take("k", 1, 2, 3)).allowed


async def test_refill_is_capped_at_burst() -> None:
    clock = FakeClock()
    rl = InMemoryRateLimiter(clock)
    assert (await rl.take("k", 3, 1, 3)).allowed
    clock.t += 3600
    assert (await rl.take("k", 3, 1, 3)).allowed
    assert not (await rl.take("k", 1, 1, 3)).allowed


async def test_refused_take_consumes_nothing_and_reports_wait() -> None:
    clock = FakeClock()
    rl = InMemoryRateLimiter(clock)
    assert (await rl.take("k", 4, rate_per_s=1, burst=10)).allowed  # 6 left
    refused = await rl.take("k", 8, 1, 10)
    assert not refused.allowed
    assert refused.retry_after_s == pytest.approx(2.0)
    assert (await rl.take("k", 6, 1, 10)).allowed  # the 6 were untouched


async def test_cost_above_burst_never_succeeds() -> None:
    rl = InMemoryRateLimiter(FakeClock())
    decision = await rl.take("k", 11, rate_per_s=1, burst=10)
    assert not decision.allowed
    assert decision.retry_after_s == pytest.approx(1.0)  # time for the missing token


async def test_keys_are_independent() -> None:
    rl = InMemoryRateLimiter(FakeClock())
    assert (await rl.take("a", 1, 1, 1)).allowed
    assert not (await rl.take("a", 1, 1, 1)).allowed
    assert (await rl.take("b", 1, 1, 1)).allowed


async def test_prune_drops_refilled_buckets() -> None:
    clock = FakeClock()
    rl = InMemoryRateLimiter(clock)
    rl._PRUNE_AT = 5  # type: ignore[misc]
    for i in range(5):
        await rl.take(f"k{i}", 1, rate_per_s=1, burst=2)
    clock.t += 10
    await rl.take("fresh", 1, 1, 2)
    assert set(rl._buckets) == {"fresh"}


# Redis implementation: Lua executed by fakeredis (needs `lupa`, a dev dependency). The Lua
# script reads the Redis server clock, so these tests use large/small rates instead of a
# fake clock.


@pytest.fixture
async def redis_limiter():  # type: ignore[no-untyped-def]
    client = fakeredis.FakeAsyncRedis()
    yield RedisRateLimiter(client)
    await client.aclose()


async def test_redis_burst_and_refusal(redis_limiter: RedisRateLimiter) -> None:
    for _ in range(3):
        assert (await redis_limiter.take("u", 1, rate_per_s=0.001, burst=3)).allowed
    refused = await redis_limiter.take("u", 1, rate_per_s=0.001, burst=3)
    assert not refused.allowed
    assert 900 < refused.retry_after_s <= 1000  # ~1 token at 0.001/s
    assert (await redis_limiter.take("other", 1, 0.001, 3)).allowed


async def test_redis_refused_take_consumes_nothing(redis_limiter: RedisRateLimiter) -> None:
    assert (await redis_limiter.take("u", 7, rate_per_s=0.001, burst=10)).allowed  # 3 left
    assert not (await redis_limiter.take("u", 5, 0.001, 10)).allowed
    assert (await redis_limiter.take("u", 3, 0.001, 10)).allowed


async def test_redis_refills_with_server_time(redis_limiter: RedisRateLimiter) -> None:
    assert (await redis_limiter.take("u", 1, rate_per_s=1000, burst=1)).allowed
    # 1000 tokens/s: by the time of the next call a token has been regenerated.
    import asyncio

    await asyncio.sleep(0.01)
    assert (await redis_limiter.take("u", 1, 1000, 1)).allowed
