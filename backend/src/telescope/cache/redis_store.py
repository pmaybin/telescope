"""Redis-backed snapshot store."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import redis.asyncio as redis

from telescope.models import Repo, Snapshot

logger = logging.getLogger(__name__)


class RedisSnapshotStore:
    """`SnapshotStore` persisted in Redis as JSON, shared across API replicas.

    The Redis key TTL (`ttl_s`) is the max-stale horizon only; freshness is still
    decided by `SnapshotService` from `Snapshot.fetched_at`.

    Single-flight remains per-process: concurrent replicas may each refresh the
    same org. Cross-replica coalescing would need a Redis lock and is out of scope.
    """

    def __init__(
        self,
        client: redis.Redis,
        *,
        key_prefix: str = "telescope:snapshot:",
        ttl_s: int = 86400,
    ) -> None:
        self._client = client
        self._prefix = key_prefix
        self._ttl_s = ttl_s

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> Snapshot | None:
        raw = await self._client.get(self._key(key))
        if raw is None:
            return None
        try:
            return _decode(raw)
        except (ValueError, TypeError, KeyError, AttributeError):
            logger.warning("corrupt snapshot payload, treating as miss", extra={"cache_key": key})
            return None

    async def set(self, key: str, snapshot: Snapshot) -> None:
        await self._client.set(self._key(key), _encode(snapshot), ex=self._ttl_s)

    async def delete(self, key: str) -> None:
        await self._client.delete(self._key(key))


def _encode(snapshot: Snapshot) -> str:
    return json.dumps(
        {
            "org": snapshot.org,
            "fetched_at": snapshot.fetched_at.isoformat(),
            "page_etags": snapshot.page_etags,
            "id": snapshot.id,
            "repos": [r.model_dump(mode="json") for r in snapshot.repos],
        }
    )


def _decode(raw: str | bytes) -> Snapshot:
    data: Any = json.loads(raw)
    return Snapshot(
        org=data["org"],
        repos=tuple(Repo.model_validate(r) for r in data["repos"]),
        fetched_at=datetime.fromisoformat(data["fetched_at"]),
        page_etags={int(k): str(v) for k, v in data["page_etags"].items()},
        id=data["id"],
    )
