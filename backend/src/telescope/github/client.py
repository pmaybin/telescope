"""Async GitHub client: concurrent page walk, conditional revalidation, retries."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import SecretStr

from telescope.errors import (
    OrgNotFound,
    UpstreamError,
    UpstreamRateLimited,
    UpstreamTimeout,
    UpstreamUnavailable,
)
from telescope.github.mapping import parse_repo
from telescope.models import LoadProgress, RateLimitState, Repo, Snapshot
from telescope.observability import metrics

if TYPE_CHECKING:
    from telescope.ratelimit import UpstreamGovernor

logger = logging.getLogger(__name__)

PER_PAGE = 100
_LINK_RE = re.compile(r'<([^>]*)>\s*;\s*rel="([^"]+)"')
_DEFAULT_SECONDARY_RETRY_S = 60


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _link_pages(header: str | None) -> dict[str, int]:
    """Return {rel: page number} from a Link header."""
    pages: dict[str, int] = {}
    if not header:
        return pages
    for url, rel in _LINK_RE.findall(header):
        values = parse_qs(urlparse(url).query).get("page")
        if values and values[0].isdigit():
            pages[rel] = int(values[0])
    return pages


def _int_header(response: httpx.Response, name: str) -> int | None:
    value = response.headers.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class SearchPreview:
    """Result of one Search API call used as a provisional first page."""

    repos: list[Repo]
    total_count: int | None
    incomplete: bool


class GitHubClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        token: SecretStr | None,
        base_url: str = "https://api.github.com",
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        backoff_max_s: float = 8.0,
        page_concurrency: int = 8,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        now: Callable[[], datetime] = _utc_now,
        governor: UpstreamGovernor | None = None,
    ) -> None:
        self._governor = governor
        self._http = http
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._backoff_max_s = backoff_max_s
        self._page_concurrency = max(1, page_concurrency)
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._now = now
        self._rate_limit = RateLimitState(authenticated=token is not None)

    @property
    def rate_limit(self) -> RateLimitState:
        return self._rate_limit

    # ------------------------------------------------------------------ public

    async def fetch_org_repos(
        self,
        org: str,
        previous: Snapshot | None = None,
        progress: LoadProgress | None = None,
    ) -> Snapshot:
        try:
            snapshot, pages, revalidated = await self._fetch(org, previous, progress)
        except UpstreamError:
            metrics.upstream_fetch("error", 0)
            raise
        metrics.upstream_fetch("revalidated" if revalidated else "full", pages)
        return snapshot

    # ------------------------------------------------------------------ walk

    async def _fetch(
        self, org: str, previous: Snapshot | None, progress: LoadProgress | None = None
    ) -> tuple[Snapshot, int, bool]:
        prev_etags = previous.page_etags if previous else {}
        prev_pages = len(prev_etags)

        def etag_for(n: int) -> str | None:
            return prev_etags.get(n) if n <= prev_pages else None

        results: dict[int, tuple[list[Repo], str | None, bool]] = {}

        first = await self._get_page(org, 1, etag_for(1))
        links = _link_pages(first.headers.get("link"))
        if "last" in links:
            total = links["last"]
        elif first.status_code == 304 and "next" not in links:
            total = max(prev_pages, 1)
        else:
            total = 1 if "next" not in links else 0  # 0 = follow `next` sequentially
        results[1] = self._page_result(first, previous, 1)
        if progress is not None:
            progress.first_page_landed(results[1][0], total or None)

        if total and total > 1:
            self._check_budget(total)
            # Charge the whole fan-out atomically *before* it starts: a walk the caller
            # cannot afford is refused without burning any further upstream calls.
            await self._govern(total - 1, pages_needed=total)
            await self._fetch_rest(org, total, etag_for, previous, results, progress)
        elif total == 0:
            n = 1
            while "next" in links:
                n += 1
                resp = await self._get_page(org, n, etag_for(n))
                links = _link_pages(resp.headers.get("link"))
                results[n] = self._page_result(resp, previous, n)
                if progress is not None:
                    progress.page_landed()
            total = n

        repos: list[Repo] = []
        etags: dict[int, str] = {}
        revalidated = False
        for n in range(1, total + 1):
            page_repos, etag, was_304 = results[n]
            repos.extend(page_repos)
            revalidated = revalidated or was_304
            if etag:
                etags[n] = etag

        fetched_at = self._now()
        all_304 = all(results[n][2] for n in range(1, total + 1))
        if previous is not None and all_304 and total == prev_pages:
            return previous.with_fetched_at(fetched_at), total, True
        snapshot = Snapshot(org=org, repos=tuple(repos), fetched_at=fetched_at, page_etags=etags)
        return snapshot, total, revalidated

    async def _fetch_rest(
        self,
        org: str,
        total: int,
        etag_for: Callable[[int], str | None],
        previous: Snapshot | None,
        results: dict[int, tuple[list[Repo], str | None, bool]],
        progress: LoadProgress | None = None,
    ) -> None:
        semaphore = asyncio.Semaphore(self._page_concurrency)

        async def one(n: int) -> None:
            async with semaphore:
                resp = await self._get_page(org, n, etag_for(n), charge=False)
            results[n] = self._page_result(resp, previous, n)
            if progress is not None:
                progress.page_landed()

        try:
            async with asyncio.TaskGroup() as tg:
                for n in range(2, total + 1):
                    tg.create_task(one(n))
        except ExceptionGroup as group:
            errors = group.exceptions
            chosen = next((e for e in errors if isinstance(e, UpstreamError)), errors[0])
            raise chosen from None

    def _check_budget(self, total: int) -> None:
        state = self._rate_limit
        if state.remaining is not None and state.remaining < total - 1:
            raise UpstreamRateLimited(
                f"Fetching {total} pages needs more quota than the {state.remaining} "
                "GitHub requests remaining.",
                retry_after=self._seconds_until(state.reset_at),
                rate_limit=state,
                reset_at=state.reset_at,
                pages_needed=total,
            )

    def _page_result(
        self, response: httpx.Response, previous: Snapshot | None, n: int
    ) -> tuple[list[Repo], str | None, bool]:
        if response.status_code == 304:
            if previous is None:
                raise UpstreamUnavailable("GitHub returned 304 to an unconditional request.")
            etag = previous.page_etags.get(n)
            return list(previous.repos[(n - 1) * PER_PAGE : n * PER_PAGE]), etag, True
        try:
            body = response.json()
            if not isinstance(body, list):
                raise ValueError("expected a JSON array")
            repos = [parse_repo(item) for item in body]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamUnavailable(f"Unexpected GitHub response for page {n}: {exc}") from exc
        return repos, response.headers.get("etag"), False

    # ------------------------------------------------------------------ http

    def _headers(self, etag: str | None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "telescope",
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        if etag:
            headers["If-None-Match"] = etag
        return headers

    async def _govern(
        self, cost: int, *, pages_needed: int | None = None, core: bool = True
    ) -> None:
        if self._governor is not None:
            # Search has its own upstream quota: the core reserve (which protects background
            # refreshes of the core walk) does not apply to it, but the per-user budget does.
            state = (
                self._rate_limit if core else RateLimitState(authenticated=self._token is not None)
            )
            await self._governor.charge(cost, state, pages_needed=pages_needed)

    # ------------------------------------------------------------------ previews (ADR-0012)

    async def preview_list(self, org: str, *, sort: str, direction: str) -> list[Repo]:
        """One list call (first 100 repos in `sort`/`direction`) used as a provisional page.
        Charged to the current principal; single attempt, never retried."""
        await self._govern(1)
        path = f"/orgs/{org}/repos"
        params: dict[str, Any] = {
            "type": "public",
            "sort": sort,
            "direction": direction,
            "per_page": PER_PAGE,
        }
        body = await self._get_once(path, params, org)
        if not isinstance(body, list):
            raise UpstreamUnavailable("Unexpected GitHub preview response.")
        return self._parse_items(body)

    async def preview_search(
        self, org: str, *, q: str, order: str, per_page: int = PER_PAGE
    ) -> SearchPreview:
        """One Search API call (top `per_page` by stars) used as a provisional page. Search has its
        own quota: its rate-limit headers never touch the core state."""
        await self._govern(1, core=False)
        params: dict[str, Any] = {
            "q": q,
            "sort": "stars",
            "order": order,
            "per_page": max(1, min(per_page, PER_PAGE)),
        }
        body = await self._get_once("/search/repositories", params, org)
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            raise UpstreamUnavailable("Unexpected GitHub search response.")
        total = body.get("total_count")
        return SearchPreview(
            repos=self._parse_items(body["items"]),
            total_count=total if isinstance(total, int) else None,
            incomplete=bool(body.get("incomplete_results", False)),
        )

    @staticmethod
    def _parse_items(items: list[Any]) -> list[Repo]:
        try:
            return [parse_repo(item) for item in items]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamUnavailable(f"Unexpected GitHub preview response: {exc}") from exc

    async def _get_once(self, path: str, params: dict[str, Any], org: str) -> Any:
        started = time.perf_counter()
        try:
            response = await self._http.get(
                self._base_url + path, params=params, headers=self._headers(None)
            )
        except httpx.TimeoutException as exc:
            metrics.github_request(None, time.perf_counter() - started)
            raise UpstreamTimeout("GitHub preview timed out.") from exc
        except httpx.TransportError as exc:
            metrics.github_request(None, time.perf_counter() - started)
            raise UpstreamUnavailable(
                f"GitHub preview failed (network error: {type(exc).__name__})."
            ) from exc
        self._observe(response, path, 0, time.perf_counter() - started)
        self._raise_for_status(response, org)
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamUnavailable("GitHub preview returned invalid JSON.") from exc

    async def _get_page(
        self, org: str, page: int, etag: str | None, *, charge: bool = True
    ) -> httpx.Response:
        if charge:
            await self._govern(1)  # once per logical page; retries are not charged again
        path = f"/orgs/{org}/repos"
        params: dict[str, Any] = {
            "type": "public",
            "sort": "full_name",
            "direction": "asc",
            "per_page": PER_PAGE,
            "page": page,
        }
        attempt = 0
        while True:
            started = time.perf_counter()
            failure: str
            timed_out = False
            try:
                response = await self._http.get(
                    self._base_url + path, params=params, headers=self._headers(etag)
                )
            except httpx.TimeoutException as exc:
                metrics.github_request(None, time.perf_counter() - started)
                failure, timed_out = f"timeout: {type(exc).__name__}", True
            except httpx.TransportError as exc:
                metrics.github_request(None, time.perf_counter() - started)
                failure = f"network error: {type(exc).__name__}"
            else:
                duration = time.perf_counter() - started
                self._observe(response, path, page, duration)
                if response.status_code < 500:
                    self._raise_for_status(response, org)
                    return response
                failure = f"HTTP {response.status_code}"

            if attempt >= self._max_retries:
                if timed_out:
                    raise UpstreamTimeout(f"GitHub timed out after {attempt + 1} attempts.")
                raise UpstreamUnavailable(
                    f"GitHub request failed after {attempt + 1} attempts ({failure})."
                )
            delay = self._rng.uniform(
                0, min(self._backoff_max_s, self._backoff_base_s * 2**attempt)
            )
            logger.warning(
                "GitHub request failed, retrying",
                extra={
                    "github_path": path,
                    "page": page,
                    "failure": failure,
                    "attempt": attempt + 1,
                    "retry_in_s": round(delay, 3),
                },
            )
            attempt += 1
            await self._sleep(delay)

    def _observe(self, response: httpx.Response, path: str, page: int, duration: float) -> None:
        resource = response.headers.get("x-ratelimit-resource")
        if resource is not None and resource != "core":
            # Search (and other resources) have their own quota: they must not overwrite the
            # core state that the budget guard and the reserve rely on.
            metrics.github_request(response.status_code, duration)
            logger.log(
                logging.INFO,
                "GitHub request",
                extra={
                    "github_path": path,
                    "page": page,
                    "status_code": response.status_code,
                    "duration_ms": round(duration * 1000, 1),
                    "ratelimit_resource": resource,
                },
            )
            return
        limit = _int_header(response, "x-ratelimit-limit")
        remaining = _int_header(response, "x-ratelimit-remaining")
        reset = _int_header(response, "x-ratelimit-reset")
        previous = self._rate_limit
        reset_at = datetime.fromtimestamp(reset, UTC) if reset is not None else previous.reset_at
        if (
            remaining is not None
            and previous.remaining is not None
            and reset_at == previous.reset_at
        ):
            # Concurrent pages can complete out of order; within one rate-limit window the
            # lowest observed `remaining` is the most recent truth.
            remaining = min(remaining, previous.remaining)
        self._rate_limit = RateLimitState(
            authenticated=self._token is not None,
            limit=limit if limit is not None else previous.limit,
            remaining=remaining if remaining is not None else previous.remaining,
            reset_at=reset_at,
        )
        metrics.github_request(response.status_code, duration)
        metrics.github_rate_limit(self._rate_limit.remaining, self._rate_limit.limit)
        logger.log(
            logging.DEBUG if response.status_code == 304 else logging.INFO,
            "GitHub request",
            extra={
                "github_path": path,
                "page": page,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 1),
                "ratelimit_remaining": self._rate_limit.remaining,
            },
        )

    def _seconds_until(self, reset_at: datetime | None) -> int:
        if reset_at is None:
            return _DEFAULT_SECONDARY_RETRY_S
        return max(1, int((reset_at - self._now()).total_seconds()))

    def _raise_for_status(self, response: httpx.Response, org: str) -> None:
        status = response.status_code
        if status < 400 or status == 304:
            return
        if status == 404:
            raise OrgNotFound(org)
        if status in (403, 429):
            state = self._rate_limit
            if response.headers.get("x-ratelimit-remaining") == "0":
                raise UpstreamRateLimited(
                    "GitHub primary rate limit exhausted.",
                    retry_after=self._seconds_until(state.reset_at),
                    rate_limit=state,
                    reset_at=state.reset_at,
                )
            retry_after = response.headers.get("retry-after")
            if retry_after is not None or "secondary rate limit" in response.text.lower():
                seconds = (
                    int(retry_after)
                    if retry_after is not None and retry_after.isdigit()
                    else _DEFAULT_SECONDARY_RETRY_S
                )
                raise UpstreamRateLimited(
                    "GitHub secondary rate limit hit.",
                    retry_after=seconds,
                    rate_limit=state,
                    secondary=True,
                )
            raise UpstreamUnavailable(f"GitHub refused the request (HTTP {status}).")
        raise UpstreamUnavailable(f"Unexpected GitHub response (HTTP {status}).")
