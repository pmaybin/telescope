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


def test_progressive_load_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("COLD_WAIT_MS", "PREVIEW_MODE", "PREWARM_ORGS"):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (defaults.cold_wait_ms, defaults.preview_mode, defaults.prewarm_orgs) == (
        1500,
        "first",
        [],
    )
    monkeypatch.setenv("COLD_WAIT_MS", "250")
    monkeypatch.setenv("PREVIEW_MODE", "per-query")
    monkeypatch.setenv("PREWARM_ORGS", "google, microsoft")
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (s.cold_wait_ms, s.preview_mode, s.prewarm_orgs) == (
        250,
        "per-query",
        ["google", "microsoft"],
    )
