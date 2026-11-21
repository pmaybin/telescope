"""Redis token bucket: one atomic Lua script, so limits hold across API replicas."""

from __future__ import annotations

import redis.asyncio as redis

from telescope.ratelimit.limiter import Decision

# KEYS[1] bucket; ARGV: cost, rate_per_s, burst. Uses the Redis server clock so replicas agree.
# Returns {allowed, retry_after_ms}.
_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local cost = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local burst = tonumber(ARGV[3])
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = burst
  ts = now
end
tokens = math.min(burst, tokens + math.max(0, now - ts) * rate)
local allowed = 0
local retry_ms = 0
if cost <= tokens then
  tokens = tokens - cost
  allowed = 1
elseif rate > 0 then
  retry_ms = math.ceil((cost - tokens) / rate * 1000)
else
  retry_ms = 3600000
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
if rate > 0 then
  redis.call('PEXPIRE', KEYS[1], math.ceil(burst / rate * 1000) + 1000)
end
return {allowed, retry_ms}
"""


class RedisRateLimiter:
    def __init__(self, client: redis.Redis, *, key_prefix: str = "telescope:rl:") -> None:
        self._prefix = key_prefix
        self._script = client.register_script(_LUA)

    async def take(self, key: str, cost: float, rate_per_s: float, burst: float) -> Decision:
        allowed, retry_ms = await self._script(
            keys=[self._prefix + key], args=[cost, rate_per_s, burst]
        )
        if int(allowed):
            return Decision(True)
        return Decision(False, int(retry_ms) / 1000)
