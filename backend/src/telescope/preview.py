"""Provisional first page for a cold load (ADR-0012).

While the snapshot walk runs, one cheap upstream call (the "preview") usually returns exactly
the first page our complete snapshot will serve. Previews are capped (`PREVIEW_MODE`), charged
to the principal that started the load, cached on the flight (polling costs nothing) and can
only ever degrade to "no items": they never fail the request or the walk.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from telescope.auth.principal import SYSTEM, Principal, current_principal
from telescope.cache.service import Flight
from telescope.github.client import PER_PAGE, GitHubClient
from telescope.models import (
    LANGUAGE_NONE,
    Repo,
    RepoQuery,
    RepoType,
    Snapshot,
    SortField,
    SortOrder,
)
from telescope.models import ProvisionalReason as Reason
from telescope.observability import metrics
from telescope.query import query_hash, run_query

logger = logging.getLogger(__name__)

PreviewMode = Literal["off", "first", "per-query"]

_LIST_SORT = {SortField.name: "full_name", SortField.updated: "updated", SortField.pushed: "pushed"}


@dataclass(frozen=True, slots=True)
class PreviewData:
    """Raw upstream result of one preview call."""

    repos: tuple[Repo, ...]
    total: int | None  # Search total_count; None for list previews
    complete: bool  # the upstream result is the whole matching set (< one full page)


@dataclass(frozen=True, slots=True)
class Provisional:
    items: list[Repo]
    total: int | None
    reason: Reason | None


def search_query(org: str, query: RepoQuery) -> str | None:
    """Translate filters to Search qualifiers; None when they cannot be expressed."""
    parts = [f"org:{org}"]
    if query.type is RepoType.all:
        parts.append("fork:true")
    elif query.type is RepoType.forks:
        parts.append("fork:only")
    # sources: no fork qualifier; Search excludes forks by default.
    if query.archived is not None:
        parts.append(f"archived:{'true' if query.archived else 'false'}")
    if query.min_stars is not None:
        parts.append(f"stars:>={query.min_stars}")
    if query.language is not None:
        if query.language.casefold() == LANGUAGE_NONE or '"' in query.language:
            return None
        parts.append(f'language:"{query.language}"')
    return " ".join(parts)


class PreviewService:
    def __init__(
        self,
        github: GitHubClient,
        *,
        mode: PreviewMode = "first",
        timeout_s: float = 5.0,
    ) -> None:
        self._github = github
        self._mode = mode
        self._timeout = timeout_s

    def _task(
        self, org: str, query: RepoQuery, flight: Flight, qhash: str
    ) -> asyncio.Task[Any] | None:
        task = flight.previews.get(qhash)
        if task is None:
            if query.sort is SortField.stars and search_query(org, query) is None:
                return None
            bare = query.model_copy(update={"cursor": None, "offset": None})
            task = asyncio.ensure_future(self._run(org, bare, self._charged(flight)))
            task.add_done_callback(_mark_retrieved)
            flight.previews[qhash] = task
        return task

    async def provisional(self, org: str, query: RepoQuery, flight: Flight) -> Provisional:
        qhash = query_hash(query)
        bare = query.model_copy(update={"cursor": None, "offset": None})

        # Free path: the walk's own page 1 *is* the name-asc first page (0 extra calls).
        if query.sort is SortField.name and query.effective_order is SortOrder.asc:
            page1 = flight.progress.first_page
            if page1 is None:
                return Provisional([], None, "preview-unavailable")  # page 1 not here yet
            total_pages = flight.progress.pages_total
            data = PreviewData(page1, None, complete=total_pages == 1 or len(page1) < PER_PAGE)
            return self._evaluate(org, bare, data, flight, qhash, free=True)

        if self._mode == "off":
            self._record(flight, qhash, "disabled")
            return Provisional([], None, "preview-disabled")

        if self._mode == "first":
            if flight.starter_hash is None:  # system-started load (prewarm): first asker claims
                flight.starter_hash = qhash
            if flight.starter_hash != qhash:
                self._record(flight, qhash, "skipped")
                return Provisional([], None, "preview-skipped")

        task = self._task(org, query, flight, qhash)
        if task is None:
            self._record(flight, qhash, "unavailable")
            return Provisional([], None, "preview-unavailable")
        try:
            data = await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record(flight, qhash, "unavailable", error=type(exc).__name__)
            return Provisional([], None, "preview-unavailable")
        return self._evaluate(org, bare, data, flight, qhash, free=False)

    # -- internals ---------------------------------------------------------------------

    @staticmethod
    def _charged(flight: Flight) -> Principal | None:
        """The principal charged for the preview: whoever started the load. A system-started
        load (prewarm) is not a user's doing, so the asking user pays for the one preview."""
        initiator = flight.initiator
        if initiator is not None and initiator is not SYSTEM and initiator.source != "system":
            return initiator
        return current_principal.get()

    async def _run(self, org: str, query: RepoQuery, principal: Principal | None) -> PreviewData:
        current_principal.set(principal)  # task-local: the task runs in a copied context
        async with asyncio.timeout(self._timeout):
            if query.sort is SortField.stars:
                q = search_query(org, query)
                assert q is not None
                # Search applies our filters itself (qualifiers), so `limit` results suffice;
                # 100 results measured ~2.9 s vs ~1 s for 30 (docs/research/cold-load-...).
                found = await self._github.preview_search(
                    org, q=q, order=query.effective_order.value, per_page=query.limit
                )
                complete = (
                    found.total_count is not None and found.total_count <= len(found.repos)
                ) or len(found.repos) < query.limit
                return PreviewData(
                    tuple(found.repos),
                    found.total_count,
                    complete=complete and not found.incomplete,
                )
            repos = await self._github.preview_list(
                org, sort=_LIST_SORT[query.sort], direction=query.effective_order.value
            )
            return PreviewData(tuple(repos), None, complete=len(repos) < PER_PAGE)

    def _evaluate(
        self,
        org: str,
        query: RepoQuery,
        data: PreviewData,
        flight: Flight,
        qhash: str,
        *,
        free: bool,
    ) -> Provisional:
        snapshot = Snapshot(org, data.repos, datetime.now(UTC))
        result = run_query(snapshot, query)
        matches = result.page.total or 0
        exact = matches >= query.limit or data.complete
        if (
            exact
            and query.sort in (SortField.updated, SortField.pushed)
            and query.effective_order is SortOrder.asc
        ):
            attr = "updated_at" if query.sort is SortField.updated else "pushed_at"
            # Upstream's null placement under asc differs from ours: not guaranteed exact.
            exact = all(getattr(r, attr) is not None for r in data.repos)
        if not exact:
            self._record(flight, qhash, "inexact")
            return Provisional([], data.total, "preview-inexact")
        self._record(flight, qhash, "free" if free else "exact")
        return Provisional(result.items[: query.limit], data.total, None)

    @staticmethod
    def _record(flight: Flight, qhash: str, outcome: metrics.PreviewOutcome, **extra: Any) -> None:
        """Count and log a decision once per cold load and query (polls repeat it)."""
        if qhash in flight.recorded:
            return
        flight.recorded.add(qhash)
        metrics.preview(outcome)
        logger.info(
            "provisional preview",
            extra={"org": flight.key, "preview_outcome": outcome, "query_hash": qhash, **extra},
        )


def _mark_retrieved(task: asyncio.Task[Any]) -> None:
    if not task.cancelled():
        task.exception()
