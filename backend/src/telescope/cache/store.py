"""Snapshot storage interface and the in-memory implementation."""

from __future__ import annotations

from collections import OrderedDict
from typing import Protocol

from telescope.models import Snapshot


class SnapshotStore(Protocol):
    """Where complete snapshots live. A Redis implementation can replace the in-memory one."""

    async def get(self, key: str) -> Snapshot | None: ...

    async def set(self, key: str, snapshot: Snapshot) -> None: ...

    async def delete(self, key: str) -> None: ...


class InMemorySnapshotStore:
    """Dict-backed store with an LRU bound on the number of entries."""

    def __init__(self, max_entries: int = 256) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be >= 1")
        self._max_entries = max_entries
        self._data: OrderedDict[str, Snapshot] = OrderedDict()

    async def get(self, key: str) -> Snapshot | None:
        snapshot = self._data.get(key)
        if snapshot is not None:
            self._data.move_to_end(key)
        return snapshot

    async def set(self, key: str, snapshot: Snapshot) -> None:
        self._data[key] = snapshot
        self._data.move_to_end(key)
        while len(self._data) > self._max_entries:
            self._data.popitem(last=False)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def __len__(self) -> int:
        return len(self._data)
