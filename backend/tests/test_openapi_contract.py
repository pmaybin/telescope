"""Contract drift check: fails if the committed openapi.json is out of date."""

import json

from telescope.export_openapi import DEFAULT_PATH, render


def test_committed_openapi_is_up_to_date() -> None:
    assert DEFAULT_PATH.exists(), "openapi.json missing; run `make openapi`"
    assert DEFAULT_PATH.read_text(encoding="utf-8") == render(), (
        "openapi.json is stale; run `make openapi gen-client` and commit the result"
    )


def test_repos_endpoint_declares_the_bearer_scheme() -> None:
    spec = json.loads(render())
    scheme = spec["components"]["securitySchemes"]["BearerAuth"]
    assert (scheme["type"], scheme["scheme"], scheme["bearerFormat"]) == ("http", "bearer", "JWT")
    assert spec["paths"]["/api/orgs/{org}/repos"]["get"]["security"] == [{"BearerAuth": []}]


def test_dev_token_endpoint_needs_no_bearer() -> None:
    spec = json.loads(render())
    assert "security" not in spec["paths"]["/api/dev/token"]["post"]
