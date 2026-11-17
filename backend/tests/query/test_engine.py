from __future__ import annotations

import base64
import json
import random
from datetime import UTC, datetime, timedelta

import pytest

from telescope.errors import InvalidCursor
from telescope.models import Repo, RepoQuery, Snapshot
from telescope.query import decode_cursor, encode_cursor, query_hash, run_query

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def mk(
    id: int,
    *,
    name: str | None = None,
    stars: int = 0,
    language: str | None = "Python",
    archived: bool = False,
    fork: bool = False,
    updated: int = 0,
    pushed: int | None = 0,
) -> Repo:
    n = name or f"repo{id}"
    return Repo(
        id=id,
        name=n,
        full_name=f"o/{n}",
        html_url=f"https://github.com/o/{n}",
        description=None,
        language=language,
        stars=stars,
        forks=0,
        open_issues=0,
        archived=archived,
        fork=fork,
        license=None,
        topics=[],
        created_at=T0,
        updated_at=T0 + timedelta(days=updated),
        pushed_at=None if pushed is None else T0 + timedelta(days=pushed),
    )


def snap(repos: list[Repo], sid: str = "snap1") -> Snapshot:
    return Snapshot(org="o", repos=tuple(repos), fetched_at=T0, id=sid)


def ids(result_items: list[Repo]) -> list[int]:
    return [r.id for r in result_items]


def q(**kw: object) -> RepoQuery:
    return RepoQuery.model_validate(kw)


def random_repos(n: int, seed: int = 7) -> list[Repo]:
    rnd = random.Random(seed)
    langs = ["Python", "Go", None, "rust"]
    return [
        mk(
            i,
            name=rnd.choice(["Alpha", "beta", "Gamma", "delta"]) + str(rnd.randint(0, 5)),
            stars=rnd.randint(0, 8),
            language=rnd.choice(langs),
            archived=rnd.random() < 0.3,
            fork=rnd.random() < 0.4,
            updated=rnd.randint(0, 10),
            pushed=rnd.choice([None, *range(10)]),
        )
        for i in range(1, n + 1)
    ]


# ------------------------------------------------------------------ filters


def test_language_case_insensitive_and_none() -> None:
    s = snap([mk(1, language="Python"), mk(2, language="Go"), mk(3, language=None)])
    assert ids(run_query(s, q(language="PYTHON")).items) == [1]
    assert ids(run_query(s, q(language="none", sort="name")).items) == [3]
    assert ids(run_query(s, q(language="NONE")).items) == [3]
    assert run_query(s, q(language="rust")).page.total == 0


def test_min_stars_inclusive() -> None:
    s = snap([mk(1, stars=5), mk(2, stars=10), mk(3, stars=11)])
    assert ids(run_query(s, q(min_stars=10, order="asc")).items) == [2, 3]


@pytest.mark.parametrize(
    ("archived", "expected"), [(True, [2]), (False, [1, 3]), (None, [1, 2, 3])]
)
def test_archived(archived: bool | None, expected: list[int]) -> None:
    s = snap([mk(1), mk(2, archived=True), mk(3)])
    kw = {} if archived is None else {"archived": archived}
    assert ids(run_query(s, q(order="asc", **kw)).items) == expected


@pytest.mark.parametrize(
    ("type_", "expected"), [("sources", [1, 3]), ("forks", [2]), ("all", [1, 2, 3])]
)
def test_type(type_: str, expected: list[int]) -> None:
    s = snap([mk(1), mk(2, fork=True), mk(3)])
    res = run_query(s, q(type=type_, order="asc"))
    assert ids(res.items) == expected
    assert res.page.total == len(expected)


# ------------------------------------------------------------------ sorting


@pytest.mark.parametrize("sort", ["stars", "updated", "pushed", "name"])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_each_sort_both_directions(sort: str, order: str) -> None:
    repos = [
        mk(1, name="b", stars=2, updated=2, pushed=2),
        mk(2, name="C", stars=3, updated=3, pushed=3),
        mk(3, name="a", stars=1, updated=1, pushed=1),
    ]
    res = run_query(snap(repos), q(sort=sort, order=order))
    expected = [3, 1, 2]
    if order == "desc":
        expected = expected[::-1]
    assert ids(res.items) == expected


def test_default_orders() -> None:
    repos = [mk(1, name="b", stars=1), mk(2, name="a", stars=2)]
    assert ids(run_query(snap(repos), q()).items) == [2, 1]
    assert ids(run_query(snap(repos), q(sort="name")).items) == [2, 1]
    assert ids(run_query(snap(repos), q(sort="name", order="desc")).items) == [1, 2]


@pytest.mark.parametrize(("order", "expected"), [("asc", [2, 1, 3, 4]), ("desc", [1, 2, 3, 4])])
def test_nulls_last_both_directions(order: str, expected: list[int]) -> None:
    repos = [mk(1, pushed=5), mk(2, pushed=1), mk(3, pushed=None), mk(4, pushed=None)]
    # asc: 2(1), 1(5), nulls by id; desc: 1(5), 2(1), nulls by id
    assert ids(run_query(snap(repos), q(sort="pushed", order=order)).items) == expected


@pytest.mark.parametrize("order", ["asc", "desc"])
def test_tiebreak_is_id_ascending(order: str) -> None:
    repos = [mk(5, stars=1), mk(2, stars=1), mk(9, stars=1), mk(1, stars=2)]
    res = run_query(snap(repos), q(order=order))
    expected = [1, 2, 5, 9] if order == "desc" else [2, 5, 9, 1]
    assert ids(res.items) == expected


def test_name_sort_casefolds() -> None:
    repos = [mk(1, name="beta"), mk(2, name="Alpha"), mk(3, name="Gamma")]
    assert ids(run_query(snap(repos), q(sort="name")).items) == [2, 1, 3]


# ------------------------------------------------------------------ pagination


def walk_forward(s: Snapshot, query: dict[str, object]) -> list[int]:
    out: list[int] = []
    cursor: str | None = None
    for _ in range(1000):
        kw = dict(query)
        if cursor:
            kw["cursor"] = cursor
        res = run_query(s, q(**kw))
        out += ids(res.items)
        assert res.page.has_prev == (cursor is not None and bool(res.items))
        if not res.page.has_next:
            assert res.page.next_cursor is None
            return out
        cursor = res.page.next_cursor
    raise AssertionError("did not terminate")


@pytest.mark.parametrize("limit", [1, 3, 7, 100])
@pytest.mark.parametrize(
    "query",
    [
        {"sort": "stars"},
        {"sort": "name", "order": "desc"},
        {"sort": "pushed"},
        {"sort": "pushed", "order": "asc", "language": "python"},
        {"sort": "updated", "type": "sources", "min_stars": 2},
    ],
)
def test_forward_walk_yields_every_item_once_in_order(limit: int, query: dict[str, object]) -> None:
    s = snap(random_repos(60))
    full = run_query(s, q(**query, limit=100))  # 60 repos: one page holds everything
    assert not full.page.has_next
    got = walk_forward(s, {**query, "limit": limit})
    assert got == ids(full.items)
    assert len(got) == len(set(got)) == full.page.total


@pytest.mark.parametrize("limit", [1, 4, 9])
def test_backward_walk_mirrors_forward(limit: int) -> None:
    s = snap(random_repos(50))
    query = {"sort": "pushed", "limit": limit}
    forward = walk_forward(s, query)

    # Jump to the end: walk forward to the last page, then go back.
    cursor: str | None = None
    last = run_query(s, q(**query))
    while last.page.has_next:
        cursor = last.page.next_cursor
        last = run_query(s, q(**query, cursor=cursor))
    pages = [ids(last.items)]
    while last.page.has_prev:
        last = run_query(s, q(**query, cursor=last.page.prev_cursor))
        assert last.page.has_next
        pages.append(ids(last.items))
    backward = [i for page in reversed(pages) for i in page]
    assert backward == forward


def test_prev_returns_items_in_forward_order() -> None:
    s = snap([mk(i, stars=100 - i) for i in range(1, 11)])
    p2 = run_query(s, q(limit=3, cursor=run_query(s, q(limit=3)).page.next_cursor))
    assert ids(p2.items) == [4, 5, 6]
    p1 = run_query(s, q(limit=3, cursor=p2.page.prev_cursor))
    assert ids(p1.items) == [1, 2, 3]
    assert not p1.page.has_prev
    assert p1.page.has_next


def test_limit_may_change_mid_walk() -> None:
    s = snap([mk(i, stars=100 - i) for i in range(1, 11)])
    first = run_query(s, q(limit=2))
    second = run_query(s, q(limit=5, cursor=first.page.next_cursor))
    assert ids(second.items) == [3, 4, 5, 6, 7]


def test_cursor_with_different_filters_rejected() -> None:
    s = snap(random_repos(20))
    cur = run_query(s, q(limit=2)).page.next_cursor
    with pytest.raises(InvalidCursor, match="does not match"):
        run_query(s, q(limit=2, language="go", cursor=cur))
    with pytest.raises(InvalidCursor):
        run_query(s, q(limit=2, sort="name", cursor=cur))


@pytest.mark.parametrize("bad", ["!!!", "bm90anNvbg", "W10", "e30"])
def test_garbage_cursor_rejected(bad: str) -> None:
    with pytest.raises(InvalidCursor):
        run_query(snap([mk(1)]), q(cursor=bad))


def _raw(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()


@pytest.mark.parametrize(
    "payload",
    [
        {"v": 2, "q": "x", "s": "y", "k": [1, 1], "d": "next"},
        {"v": 1, "q": "x", "s": "y", "k": [1], "d": "next"},
        {"v": 1, "q": "x", "s": "y", "k": [1, "a"], "d": "next"},
        {"v": 1, "q": "x", "s": "y", "k": [1, 1], "d": "sideways"},
        {"v": 1, "q": 5, "s": "y", "k": [1, 1], "d": "next"},
    ],
)
def test_decode_rejects_bad_shapes(payload: object) -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor(_raw(payload))


def test_wrong_value_type_for_sort_rejected() -> None:
    s = snap([mk(1)])
    from telescope.query.cursor import Cursor

    bad = encode_cursor(Cursor(query_hash(q()), "snap1", "not-an-int", 1, "next"))
    with pytest.raises(InvalidCursor):
        run_query(s, q(cursor=bad))
    bad_date = encode_cursor(Cursor(query_hash(q(sort="pushed")), "snap1", "garbage", 1, "next"))
    with pytest.raises(InvalidCursor):
        run_query(s, q(sort="pushed", cursor=bad_date))


def test_cursor_roundtrip_and_hash_ignores_limit() -> None:
    from telescope.query.cursor import Cursor

    c = Cursor("abc", "snap", None, 7, "prev")
    token = encode_cursor(c)
    assert "=" not in token
    assert decode_cursor(token) == c
    assert query_hash(q(limit=5)) == query_hash(q(limit=50))
    assert query_hash(q(language="Go")) == query_hash(q(language="go"))
    assert query_hash(q()) == query_hash(q(order="desc"))
    assert query_hash(q()) != query_hash(q(order="asc"))


def test_older_snapshot_cursor_is_served_and_flagged() -> None:
    repos = [mk(i, stars=100 - i) for i in range(1, 11)]
    first = run_query(snap(repos, "old"), q(limit=3))
    assert not first.cursor_from_older_snapshot
    res = run_query(snap(repos, "new"), q(limit=3, cursor=first.page.next_cursor))
    assert res.cursor_from_older_snapshot
    assert ids(res.items) == [4, 5, 6]


@pytest.mark.parametrize("sort", ["stars", "pushed", "name"])
def test_deleted_key_item_continues_correctly(sort: str) -> None:
    repos = [mk(i, name=f"n{i:02d}", stars=100 - i, pushed=20 - i) for i in range(1, 11)]
    first = run_query(snap(repos, "old"), q(sort=sort, limit=3))
    last_id = first.items[-1].id
    newer = [r for r in repos if r.id != last_id]
    nxt = run_query(snap(newer, "new"), q(sort=sort, limit=3, cursor=first.page.next_cursor))
    assert (
        ids(nxt.items)
        == [
            i
            for i in ids(run_query(snap(repos), q(sort=sort, limit=10)).items)
            if i not in (*ids(first.items),)
        ][:3]
    )


def test_prev_cursor_with_deleted_key_at_start() -> None:
    repos = [mk(i, stars=100 - i) for i in range(1, 11)]
    page2 = run_query(
        snap(repos, "a"),
        q(limit=3, cursor=run_query(snap(repos, "a"), q(limit=3)).page.next_cursor),
    )
    newer = [r for r in repos if r.id != page2.items[0].id]
    back = run_query(snap(newer, "b"), q(limit=3, cursor=page2.page.prev_cursor))
    assert ids(back.items) == [1, 2, 3]
    assert back.page.has_next


def test_empty_results() -> None:
    res = run_query(snap([mk(1)]), q(language="zig"))
    assert res.items == []
    assert res.page.total == 0
    assert not res.page.has_next
    assert not res.page.has_prev
    assert res.page.next_cursor is None
    assert res.page.prev_cursor is None
    empty = run_query(snap([]), q())
    assert empty.items == [] and empty.page.next_cursor is None


def test_exact_last_page_has_no_next() -> None:
    s = snap([mk(i, stars=i) for i in range(1, 7)])
    res = run_query(s, q(limit=6))
    assert not res.page.has_next
    assert res.page.next_cursor is None
