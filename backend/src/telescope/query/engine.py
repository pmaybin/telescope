"""Filter, sort and keyset-paginate a snapshot. Pure: no I/O, no shared state."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from telescope.errors import InvalidCursor
from telescope.models import (
    LANGUAGE_NONE,
    PageInfo,
    Repo,
    RepoQuery,
    RepoType,
    Snapshot,
    SortField,
    SortOrder,
)
from telescope.query.cursor import (
    Cursor,
    Direction,
    SortValue,
    decode_cursor,
    encode_cursor,
    query_hash,
)

# (is_null, directed value, id). Nulls last in both directions, id always ascending.
Key = tuple[int, Any, int]


@dataclass(frozen=True)
class QueryResult:
    items: list[Repo]
    page: PageInfo
    cursor_from_older_snapshot: bool


class _Reversed:
    """Wrapper that inverts the ordering of its value (for descending sorts)."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Reversed) and self.value == other.value

    def __lt__(self, other: _Reversed) -> bool:
        return bool(other.value < self.value)

    def __hash__(self) -> int:
        return hash(self.value)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


_SORT_VALUE: dict[SortField, Callable[[Repo], int | str | datetime | None]] = {
    SortField.stars: lambda r: r.stars,
    SortField.updated: lambda r: r.updated_at and _utc(r.updated_at),
    SortField.pushed: lambda r: r.pushed_at and _utc(r.pushed_at),
    SortField.name: lambda r: r.name.casefold(),
}


def _make_key(value: int | str | datetime | None, repo_id: int, order: SortOrder) -> Key:
    if value is None:
        return (1, 0, repo_id)
    return (0, _Reversed(value) if order is SortOrder.desc else value, repo_id)


def _repo_key(repo: Repo, sort: SortField, order: SortOrder) -> Key:
    return _make_key(_SORT_VALUE[sort](repo), repo.id, order)


def _to_json_value(value: int | str | datetime | None) -> SortValue:
    return value.isoformat() if isinstance(value, datetime) else value


def _from_cursor(cursor: Cursor, sort: SortField, order: SortOrder) -> Key:
    raw = cursor.sort_value
    value: int | str | datetime | None
    if raw is None:
        value = None
    elif sort is SortField.stars:
        if not isinstance(raw, int):
            raise InvalidCursor("cursor is malformed")
        value = raw
    elif sort is SortField.name:
        if not isinstance(raw, str):
            raise InvalidCursor("cursor is malformed")
        value = raw
    else:
        if not isinstance(raw, str):
            raise InvalidCursor("cursor is malformed")
        try:
            value = _utc(datetime.fromisoformat(raw))
        except ValueError as exc:
            raise InvalidCursor("cursor is malformed") from exc
    return _make_key(value, cursor.id, order)


def _matches(repo: Repo, query: RepoQuery) -> bool:
    if query.language is not None:
        wanted = query.language.casefold()
        if wanted == LANGUAGE_NONE:
            if repo.language is not None:
                return False
        elif repo.language is None or repo.language.casefold() != wanted:
            return False
    if query.min_stars is not None and repo.stars < query.min_stars:
        return False
    if query.archived is not None and repo.archived != query.archived:
        return False
    if query.type is RepoType.sources and repo.fork:
        return False
    return not (query.type is RepoType.forks and not repo.fork)


def _cursor_for(
    repo: Repo, sort: SortField, qhash: str, snapshot_id: str, direction: Direction
) -> str:
    return encode_cursor(
        Cursor(
            query_hash=qhash,
            snapshot_id=snapshot_id,
            sort_value=_to_json_value(_SORT_VALUE[sort](repo)),
            id=repo.id,
            direction=direction,
        )
    )


def run_query(snapshot: Snapshot, query: RepoQuery) -> QueryResult:
    sort, order = query.sort, query.effective_order
    qhash = query_hash(query)

    cursor: Cursor | None = None
    if query.cursor is not None:
        cursor = decode_cursor(query.cursor)
        if cursor.query_hash != qhash:
            raise InvalidCursor("cursor does not match the current filters/sort")
    older = cursor is not None and cursor.snapshot_id != snapshot.id

    ordered = sorted(
        (r for r in snapshot.repos if _matches(r, query)),
        key=lambda r: _repo_key(r, sort, order),
    )
    keys = [_repo_key(r, sort, order) for r in ordered]
    total = len(ordered)
    limit = query.limit

    if cursor is None:
        start, end = 0, min(limit, total)
    else:
        key = _from_cursor(cursor, sort, order)
        if cursor.direction == "next":
            start = bisect_right(keys, key)
            end = min(start + limit, total)
        else:
            end = bisect_left(keys, key)
            start = max(0, end - limit)

    items = ordered[start:end]
    has_next = bool(items) and end < total
    has_prev = bool(items) and start > 0
    page = PageInfo(
        limit=limit,
        total=total,
        has_next=has_next,
        has_prev=has_prev,
        next_cursor=_cursor_for(items[-1], sort, qhash, snapshot.id, "next") if has_next else None,
        prev_cursor=_cursor_for(items[0], sort, qhash, snapshot.id, "prev") if has_prev else None,
    )
    return QueryResult(items=items, page=page, cursor_from_older_snapshot=older)
