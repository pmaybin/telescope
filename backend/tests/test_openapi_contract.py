"""Contract drift check: fails if the committed openapi.json is out of date."""

from telescope.export_openapi import DEFAULT_PATH, render


def test_committed_openapi_is_up_to_date() -> None:
    assert DEFAULT_PATH.exists(), "openapi.json missing; run `make openapi`"
    assert DEFAULT_PATH.read_text(encoding="utf-8") == render(), (
        "openapi.json is stale; run `make openapi gen-client` and commit the result"
    )
