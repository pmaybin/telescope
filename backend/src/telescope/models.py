"""API contract and core domain types.

This module is the single source of truth for the public contract (exported to
`openapi.json`) and for the shapes passed between the GitHub client, the cache
and the query engine. Keep it dependency-free (no httpx, no FastAPI).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ORG_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$"
LANGUAGE_NONE = "none"
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
MAX_OFFSET = 100_000


# --------------------------------------------------------------------------- query


class RepoType(StrEnum):
    all = "all"
    sources = "sources"
    forks = "forks"


class SortField(StrEnum):
    stars = "stars"
    updated = "updated"
    pushed = "pushed"
    name = "name"


class SortOrder(StrEnum):
    asc = "asc"
    desc = "desc"


DEFAULT_ORDER: dict[SortField, SortOrder] = {
    SortField.stars: SortOrder.desc,
    SortField.updated: SortOrder.desc,
    SortField.pushed: SortOrder.desc,
    SortField.name: SortOrder.asc,
}


class RepoQuery(BaseModel):
    """Query parameters for `GET /api/orgs/{org}/repos`."""

    model_config = ConfigDict(extra="forbid")

    language: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=64,
            description=(
                "Primary language, case-insensitive exact match. "
                f"Use `{LANGUAGE_NONE}` for repositories with no detected language."
            ),
        ),
    ] = None
    min_stars: Annotated[int | None, Field(ge=0, description="Minimum star count (inclusive).")] = (
        None
    )
    archived: Annotated[
        bool | None, Field(description="Filter by archived state. Omit for both.")
    ] = None
    type: Annotated[RepoType, Field(description="Source repositories, forks, or all.")] = (
        RepoType.all
    )
    sort: Annotated[
        SortField,
        Field(description="`updated` = GitHub `updated_at`; `pushed` = last push (`pushed_at`)."),
    ] = SortField.stars
    order: Annotated[
        SortOrder | None,
        Field(description="Defaults to `desc` for stars/updated/pushed and `asc` for name."),
    ] = None
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT, description="Page size.")] = DEFAULT_LIMIT
    cursor: Annotated[
        str | None,
        Field(
            max_length=1024,
            description="Opaque cursor from `page.next_cursor` or `page.prev_cursor`.",
        ),
    ] = None
    offset: Annotated[
        int | None,
        Field(
            ge=0,
            le=MAX_OFFSET,
            description=(
                "Zero-based offset into the filtered, sorted list. Mutually exclusive "
                "with `cursor` (400 `invalid-pagination` if both are given)."
            ),
        ),
    ] = None

    @property
    def effective_order(self) -> SortOrder:
        return self.order or DEFAULT_ORDER[self.sort]

    @model_validator(mode="after")
    def _normalise(self) -> Self:
        if self.language is not None:
            self.language = self.language.strip() or None
        return self


# --------------------------------------------------------------------------- records


class License(BaseModel):
    spdx_id: str | None = Field(
        description="SPDX identifier; null when GitHub reports NOASSERTION."
    )
    name: str


class Repo(BaseModel):
    """A repository, normalised: empty strings from GitHub become null."""

    model_config = ConfigDict(frozen=True)

    id: int
    name: str
    full_name: str
    html_url: str
    description: str | None
    language: str | None
    stars: int
    forks: int
    open_issues: int
    archived: bool
    fork: bool
    license: License | None
    topics: list[str]
    created_at: datetime | None
    updated_at: datetime | None
    pushed_at: datetime | None


# --------------------------------------------------------------------------- response


class PageInfo(BaseModel):
    limit: int
    total: int = Field(description="Number of repositories matching the filters.")
    has_next: bool
    has_prev: bool
    next_cursor: str | None
    prev_cursor: str | None
    offset: int | None = Field(
        default=None, description="Offset of this page in offset mode; null in cursor mode."
    )


class SnapshotInfo(BaseModel):
    id: str = Field(description="Content hash of the upstream dataset this page was computed from.")
    fetched_at: datetime = Field(description="When the dataset was last fetched or revalidated.")
    repo_count: int = Field(description="Repositories in the org before filtering.")
    stale: bool = Field(
        description="True when served past its TTL because GitHub was unavailable or rate limited."
    )
    cursor_from_older_snapshot: bool = Field(
        description="True when the cursor was issued against a different snapshot; "
        "rows whose sort key changed may have moved."
    )


class RateLimitInfo(BaseModel):
    authenticated: bool
    limit: int | None
    remaining: int | None
    reset_at: datetime | None


class RepoPage(BaseModel):
    org: str
    items: list[Repo]
    page: PageInfo
    snapshot: SnapshotInfo
    rate_limit: RateLimitInfo


class Problem(BaseModel):
    """RFC 9457 problem details (`application/problem+json`)."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    retry_after: int | None = Field(default=None, description="Seconds; mirrors `Retry-After`.")


# --------------------------------------------------------------------------- internal


@dataclass(frozen=True, slots=True)
class RateLimitState:
    """Last observed GitHub rate-limit headers."""

    authenticated: bool
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None

    def to_info(self) -> RateLimitInfo:
        return RateLimitInfo(
            authenticated=self.authenticated,
            limit=self.limit,
            remaining=self.remaining,
            reset_at=self.reset_at,
        )


@dataclass(frozen=True, slots=True)
class Snapshot:
    """An immutable, complete copy of an org's public repositories.

    Only ever built from a *complete* pagination walk: partial data is never
    represented as a Snapshot, so it can never be cached.
    """

    org: str
    repos: tuple[Repo, ...]
    fetched_at: datetime
    # Per-page ETags keyed by page number, used for conditional revalidation.
    page_etags: dict[int, str] = field(default_factory=dict, compare=False)
    id: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", snapshot_id(self.repos))

    def with_fetched_at(self, fetched_at: datetime) -> Snapshot:
        return Snapshot(self.org, self.repos, fetched_at, dict(self.page_etags), self.id)


def snapshot_id(repos: tuple[Repo, ...]) -> str:
    """Content hash: identical upstream data yields the same id, so cursors survive
    a revalidation that changed nothing."""
    h = hashlib.sha256()
    for r in sorted(repos, key=lambda r: r.id):
        h.update(r.model_dump_json().encode())
    return h.hexdigest()[:16]
