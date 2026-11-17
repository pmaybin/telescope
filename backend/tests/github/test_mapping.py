from __future__ import annotations

from fixtures.github import make_repo_json
from telescope.github.mapping import parse_repo


def test_normalises_empty_strings_and_noassertion() -> None:
    repo = parse_repo(
        make_repo_json(
            1,
            "  padded ",
            description="   ",
            language="",
            license={"spdx_id": "NOASSERTION", "name": "Other"},
            pushed_at=None,
        )
    )
    assert repo.name == "padded"
    assert repo.description is None
    assert repo.language is None
    assert repo.license is not None
    assert repo.license.spdx_id is None
    assert repo.pushed_at is None


def test_missing_license_and_defaults() -> None:
    raw = make_repo_json(2, license=None)
    del raw["topics"]
    repo = parse_repo(raw)
    assert repo.license is None
    assert repo.topics == []
    assert (repo.stars, repo.forks, repo.open_issues) == (2, 1, 2)
    assert repo.created_at is not None
    assert repo.created_at.tzinfo is not None
