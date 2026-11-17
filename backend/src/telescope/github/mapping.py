"""Map raw GitHub repository JSON to the normalised `Repo` domain type."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from telescope.models import License, Repo


def _text(value: Any) -> str | None:
    """Strip a string; empty or non-string values become None."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _dt(value: Any) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _license(raw: Any) -> License | None:
    if not isinstance(raw, dict):
        return None
    spdx = _text(raw.get("spdx_id"))
    if spdx == "NOASSERTION":
        spdx = None
    return License(spdx_id=spdx, name=_text(raw.get("name")) or spdx or "Other")


def parse_repo(raw: dict[str, Any]) -> Repo:
    topics = raw.get("topics") or []
    return Repo(
        id=raw["id"],
        name=str(raw["name"]).strip(),
        full_name=str(raw["full_name"]).strip(),
        html_url=str(raw["html_url"]).strip(),
        description=_text(raw.get("description")),
        language=_text(raw.get("language")),
        stars=raw.get("stargazers_count") or 0,
        forks=raw.get("forks_count") or 0,
        open_issues=raw.get("open_issues_count") or 0,
        archived=bool(raw.get("archived", False)),
        fork=bool(raw.get("fork", False)),
        license=_license(raw.get("license")),
        topics=[t for t in (_text(x) for x in topics) if t],
        created_at=_dt(raw.get("created_at")),
        updated_at=_dt(raw.get("updated_at")),
        pushed_at=_dt(raw.get("pushed_at")),
    )
