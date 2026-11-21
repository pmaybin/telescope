from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from telescope.cache import InMemorySnapshotStore, SnapshotService
from telescope.models import LoadProgress, Snapshot


async def test_walks_are_capped_globally() -> None:
    running = 0
    peak = 0

    async def fetcher(
        org: str, previous: Snapshot | None, progress: LoadProgress | None = None
    ) -> Snapshot:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        for _ in range(5):
            await asyncio.sleep(0)
        running -= 1
        return Snapshot(org=org, repos=(), fetched_at=datetime.now(UTC), page_etags={})

    service = SnapshotService(InMemorySnapshotStore(), fetcher, max_concurrent_walks=2)
    results = await asyncio.gather(*(service.get(f"org{i}") for i in range(6)))
    assert len(results) == 6  # the rest waited; none failed
    assert peak == 2
    await service.aclose()
