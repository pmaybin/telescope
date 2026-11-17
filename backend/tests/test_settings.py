import pytest

from telescope.settings import Settings


def test_empty_token_becomes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "")
    assert Settings().github_token is None


def test_token_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "abc")
    token = Settings().github_token
    assert token is not None
    assert token.get_secret_value() == "abc"
