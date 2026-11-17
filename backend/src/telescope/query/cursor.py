"""Opaque pagination cursor: ``base64url(json)`` without padding."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from telescope.errors import InvalidCursor
from telescope.models import RepoQuery

CURSOR_VERSION = 1

Direction = Literal["next", "prev"]
SortValue = int | str | None


@dataclass(frozen=True, slots=True)
class Cursor:
    query_hash: str
    snapshot_id: str
    sort_value: SortValue
    id: int
    direction: Direction


def query_hash(query: RepoQuery) -> str:
    """Short hash of the normalised filters, sort and effective order.

    `limit`, `cursor` and `offset` are deliberately excluded so the page size may change
    mid-walk.
    """
    normalised = {
        "language": query.language.casefold() if query.language else None,
        "min_stars": query.min_stars,
        "archived": query.archived,
        "type": query.type.value,
        "sort": query.sort.value,
        "order": query.effective_order.value,
    }
    raw = json.dumps(normalised, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def encode_cursor(cursor: Cursor) -> str:
    payload = {
        "v": CURSOR_VERSION,
        "q": cursor.query_hash,
        "s": cursor.snapshot_id,
        "k": [cursor.sort_value, cursor.id],
        "d": cursor.direction,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_cursor(token: str) -> Cursor:
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii") + b"=" * (-len(token) % 4))
        data = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeError) as exc:
        raise InvalidCursor("cursor is malformed") from exc
    if not isinstance(data, dict):
        raise InvalidCursor("cursor is malformed")
    if data.get("v") != CURSOR_VERSION:
        raise InvalidCursor("unsupported cursor version")
    q, s, k, d = data.get("q"), data.get("s"), data.get("k"), data.get("d")
    if not isinstance(q, str) or not isinstance(s, str) or d not in ("next", "prev"):
        raise InvalidCursor("cursor is malformed")
    if not isinstance(k, list) or len(k) != 2:
        raise InvalidCursor("cursor is malformed")
    value, ident = k
    if isinstance(value, bool) or not (value is None or isinstance(value, int | str)):
        raise InvalidCursor("cursor is malformed")
    if isinstance(ident, bool) or not isinstance(ident, int):
        raise InvalidCursor("cursor is malformed")
    return Cursor(query_hash=q, snapshot_id=s, sort_value=value, id=ident, direction=d)
