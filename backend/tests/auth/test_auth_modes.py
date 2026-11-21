from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.requests import Request

from fixtures.apps import AppFactory
from fixtures.github import mock_pages
from telescope.auth import Authenticator
from telescope.settings import Settings

URL = "/api/orgs/acme/repos"
SECRET = "unit-test-secret-unit-test-secret-1234"
JWKS_URL = "https://idp.test/.well-known/jwks.json"
ISSUER = "https://idp.test/"
AUDIENCE = "telescope-prod"


def dev_token(secret: str = SECRET, **overrides: Any) -> str:
    now = int(time.time())
    claims = {
        "sub": "alice",
        "iss": "telescope-dev",
        "aud": "telescope",
        "iat": now,
        "exp": now + 600,
        **overrides,
    }
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, secret, "HS256")


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ dev mode


async def test_dev_mode_requires_a_token(app_factory: AppFactory, mock: respx.MockRouter) -> None:
    mock_pages(mock, 1)
    r = await app_factory(auth_dev_secret=SECRET).client.get(URL)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"].endswith("/unauthorized")


async def test_dev_token_round_trip(app_factory: AppFactory, mock: respx.MockRouter) -> None:
    mock_pages(mock, 1)
    client = app_factory().client  # random per-process secret
    minted = await client.post("/api/dev/token", json={"sub": "carol"})
    assert minted.status_code == 200
    body = minted.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert (claims["sub"], claims["iss"], claims["aud"]) == ("carol", "telescope-dev", "telescope")
    assert claims["exp"] - claims["iat"] == 3600

    r = await client.get(URL, headers=bearer(body["access_token"]))
    assert r.status_code == 200


async def test_dev_token_defaults_and_validates_sub(app_factory: AppFactory) -> None:
    client = app_factory().client
    default = await client.post("/api/dev/token")
    sub = jwt.decode(default.json()["access_token"], options={"verify_signature": False})["sub"]
    assert sub == "dev-user"
    assert (await client.post("/api/dev/token", json={"sub": ""})).status_code == 422
    assert (await client.post("/api/dev/token", json={"sub": "x" * 65})).status_code == 422


@pytest.mark.parametrize("mode", ["none", "jwt", "tailscale"])
async def test_dev_token_is_404_outside_dev_mode(app_factory: AppFactory, mode: str) -> None:
    extra: dict[str, Any] = {}
    if mode == "jwt":
        extra = {"auth_jwks_url": JWKS_URL, "auth_jwt_issuer": ISSUER, "auth_jwt_audience": "a"}
    r = await app_factory(auth_mode=mode, **extra).client.post("/api/dev/token")
    assert r.status_code == 404


async def test_expired_dev_token_is_rejected(app_factory: AppFactory) -> None:
    client = app_factory(auth_dev_secret=SECRET).client
    r = await client.get(URL, headers=bearer(dev_token(exp=int(time.time()) - 10)))
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


@pytest.mark.parametrize(
    "token",
    [
        dev_token(aud="someone-else"),
        dev_token(iss="evil"),
        dev_token(secret="a-different-secret-a-different-secret-12"),
        dev_token(sub=None),
        "not-a-jwt",
    ],
)
async def test_bad_dev_tokens_are_rejected(app_factory: AppFactory, token: str) -> None:
    client = app_factory(auth_dev_secret=SECRET).client
    assert (await client.get(URL, headers=bearer(token))).status_code == 401


async def test_public_paths_need_no_credentials(app_factory: AppFactory) -> None:
    client = app_factory().client
    for path in ("/healthz", "/docs", "/openapi.json"):
        assert (await client.get(path)).status_code == 200, path


# ------------------------------------------------------------------ jwt mode


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks_for(key: rsa.RSAPrivateKey, kid: str = "k1") -> dict[str, Any]:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": kid, "use": "sig", "alg": "RS256"}]}


def gateway_token(key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    now = int(time.time())
    claims = {"sub": "gw-user", "iss": ISSUER, "aud": AUDIENCE, "exp": now + 600, **overrides}
    return jwt.encode(claims, key, "RS256", headers={"kid": "k1"})


JWT_SETTINGS = {
    "auth_mode": "jwt",
    "auth_jwks_url": JWKS_URL,
    "auth_jwt_issuer": ISSUER,
    "auth_jwt_audience": AUDIENCE,
}


async def test_jwt_mode_accepts_gateway_token_and_caches_jwks(
    app_factory: AppFactory, mock: respx.MockRouter, rsa_key: rsa.RSAPrivateKey
) -> None:
    mock_pages(mock, 1)
    jwks = mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_for(rsa_key)))
    client = app_factory(**JWT_SETTINGS).client
    for _ in range(3):
        r = await client.get(URL, headers=bearer(gateway_token(rsa_key)))
        assert r.status_code == 200
    assert jwks.call_count == 1


@pytest.mark.parametrize(
    "overrides",
    [{"aud": "other"}, {"iss": "https://evil/"}, {"exp": int(time.time()) - 5}],
)
async def test_jwt_mode_verifies_claims(
    app_factory: AppFactory,
    mock: respx.MockRouter,
    rsa_key: rsa.RSAPrivateKey,
    overrides: dict[str, Any],
) -> None:
    mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_for(rsa_key)))
    client = app_factory(**JWT_SETTINGS).client
    r = await client.get(URL, headers=bearer(gateway_token(rsa_key, **overrides)))
    assert r.status_code == 401


async def test_jwt_mode_rejects_token_signed_by_unknown_key(
    app_factory: AppFactory, mock: respx.MockRouter, rsa_key: rsa.RSAPrivateKey
) -> None:
    mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_for(rsa_key)))
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = app_factory(**JWT_SETTINGS).client
    assert (await client.get(URL, headers=bearer(gateway_token(other)))).status_code == 401


async def test_jwt_mode_rejects_hs256_key_confusion(
    app_factory: AppFactory, mock: respx.MockRouter, rsa_key: rsa.RSAPrivateKey
) -> None:
    """Classic attack: sign HS256 using the (public) RSA key bytes as the HMAC secret."""
    mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_for(rsa_key)))
    public_pem = rsa_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    payload = b64(
        json.dumps(
            {"sub": "evil", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 600}
        ).encode()
    )
    signature = hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    forged = f"{header}.{payload}.{b64(signature)}"
    client = app_factory(**JWT_SETTINGS).client
    assert (await client.get(URL, headers=bearer(forged))).status_code == 401


async def test_jwt_mode_rejects_hs256_and_none_tokens(
    app_factory: AppFactory, mock: respx.MockRouter, rsa_key: rsa.RSAPrivateKey
) -> None:
    mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks_for(rsa_key)))
    client = app_factory(**JWT_SETTINGS).client
    hs = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 60},
        SECRET,
        "HS256",
        headers={"kid": "k1"},
    )
    unsigned = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "exp": int(time.time()) + 60},
        None,
        "none",
        headers={"kid": "k1"},
    )
    for token in (hs, unsigned):
        assert (await client.get(URL, headers=bearer(token))).status_code == 401


async def test_jwt_mode_ignores_dev_tokens(app_factory: AppFactory, mock: respx.MockRouter) -> None:
    mock.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": []}))
    client = app_factory(auth_dev_secret=SECRET, **JWT_SETTINGS).client
    assert (await client.get(URL, headers=bearer(dev_token()))).status_code == 401


async def test_jwt_mode_unreachable_jwks_is_401_not_500(
    app_factory: AppFactory, mock: respx.MockRouter, rsa_key: rsa.RSAPrivateKey
) -> None:
    mock.get(JWKS_URL).mock(return_value=httpx.Response(503))
    client = app_factory(**JWT_SETTINGS).client
    assert (await client.get(URL, headers=bearer(gateway_token(rsa_key)))).status_code == 401


def test_jwt_mode_requires_configuration() -> None:
    with pytest.raises(ValueError, match="AUTH_JWKS_URL"):
        Settings(auth_mode="jwt")


# ------------------------------------------------------------------ tailscale


async def test_tailscale_header_trusted_only_from_trusted_proxy(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_pages(mock, 1)
    headers = {"Tailscale-User-Login": "bob@example.com"}
    trusted = app_factory(
        peer="100.64.0.7", auth_mode="tailscale", auth_trusted_proxies="100.64.0.0/10"
    ).client
    assert (await trusted.get(URL, headers=headers)).status_code == 200
    assert (await trusted.get(URL)).status_code == 401  # header missing

    untrusted = app_factory(
        peer="203.0.113.9", auth_mode="tailscale", auth_trusted_proxies="100.64.0.0/10"
    ).client
    r = await untrusted.get(URL, headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


# ------------------------------------------------------------------ none mode / client IP


def request_from(peer: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request(
        {"type": "http", "client": (peer, 1), "headers": headers, "method": "GET", "path": "/"}
    )


@pytest.mark.parametrize(
    ("peer", "xff", "expected"),
    [
        ("198.51.100.1", "6.6.6.6", "198.51.100.1"),  # untrusted peer: XFF ignored
        ("10.0.0.2", "203.0.113.5", "203.0.113.5"),  # trusted peer: honoured
        ("10.0.0.2", "6.6.6.6, 203.0.113.5", "203.0.113.5"),  # forged prefix ignored
        ("10.0.0.2", "203.0.113.5, 10.0.0.9", "203.0.113.5"),  # chain of trusted proxies
        ("10.0.0.2", "garbage", "10.0.0.2"),  # malformed: fall back to the peer
        ("10.0.0.2", None, "10.0.0.2"),
    ],
)
def test_client_ip_honours_forwarded_for_only_from_trusted_proxies(
    peer: str, xff: str | None, expected: str
) -> None:
    auth = Authenticator(
        Settings(auth_mode="none", auth_trusted_proxies="10.0.0.0/8"),
        http=httpx.AsyncClient(),
    )
    assert auth.client_ip(request_from(peer, xff)) == expected


async def test_none_mode_needs_no_credentials(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_pages(mock, 1)
    assert (await app_factory(auth_mode="none").client.get(URL)).status_code == 200


# ------------------------------------------------------------------ cross-site, allowlist


async def test_cross_site_requests_are_forbidden(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    routes = mock_pages(mock, 1)
    client = app_factory(auth_mode="none").client
    r = await client.get(URL, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert r.json()["type"].endswith("/cross-site-request")
    assert routes[1].call_count == 0
    for site in ("same-origin", "same-site", "none"):
        assert (await client.get(URL, headers={"Sec-Fetch-Site": site})).status_code == 200


async def test_cross_site_guard_covers_dev_token(app_factory: AppFactory) -> None:
    r = await app_factory().client.post("/api/dev/token", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


async def test_org_allowlist_blocks_before_any_work(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    routes = mock_pages(mock, 1)
    client = app_factory(auth_mode="none", org_allowlist="Acme, other").client
    blocked = await client.get("/api/orgs/evil/repos")
    assert blocked.status_code == 403
    assert blocked.json()["type"].endswith("/org-not-allowed")
    assert routes[1].call_count == 0
    assert (await client.get(URL)).status_code == 200  # case-insensitive


async def test_empty_allowlist_allows_everything(
    app_factory: AppFactory, mock: respx.MockRouter
) -> None:
    mock_pages(mock, 1)
    assert (await app_factory(auth_mode="none").client.get(URL)).status_code == 200


def test_list_settings_accept_comma_separated_and_json() -> None:
    assert Settings(org_allowlist="a, b ,,c").org_allowlist == ["a", "b", "c"]
    assert Settings(org_allowlist='["a","b"]').org_allowlist == ["a", "b"]
    assert Settings(auth_trusted_proxies="10.0.0.0/8,::1").auth_trusted_proxies == [
        "10.0.0.0/8",
        "::1",
    ]
    assert Settings(org_allowlist="").org_allowlist == []
