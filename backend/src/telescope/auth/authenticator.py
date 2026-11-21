"""Resolve a request to a `Principal` according to `AUTH_MODE` (ADR-0013)."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import secrets
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
import jwt
from fastapi import Request

from telescope.auth.principal import Principal
from telescope.errors import Unauthorized
from telescope.settings import Settings

logger = logging.getLogger(__name__)

DEV_ISSUER = "telescope-dev"
DEV_AUDIENCE = "telescope"
DEV_TOKEN_TTL_S = 3600
DEFAULT_DEV_SUB = "dev-user"
# Asymmetric only: never HS* (key confusion with a public JWKS) and never "none".
ASYMMETRIC_ALGORITHMS = [
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
]
_JWKS_TTL_S = 300
_JWKS_MIN_REFETCH_S = 30

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def _parse_networks(values: Sequence[str]) -> list[IPNetwork]:
    return [ipaddress.ip_network(v, strict=False) for v in values]


def _ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


class JwksKeys:
    """Fetches and caches the gateway's JWKS (async, via httpx), refetching on an unknown kid."""

    def __init__(
        self, url: str, http: httpx.AsyncClient, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._url = url
        self._http = http
        self._clock = clock
        self._keys: dict[str, Any] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    async def key_for(self, kid: str | None) -> Any:
        key = self._lookup(kid)
        if key is not None and not self._expired():
            return key
        async with self._lock:
            key = self._lookup(kid)
            if key is None or self._expired():
                await self._refresh()
                key = self._lookup(kid)
        if key is None:
            raise Unauthorized("Signing key not found.")
        return key

    def _expired(self) -> bool:
        return self._fetched_at is None or self._clock() - self._fetched_at > _JWKS_TTL_S

    def _lookup(self, kid: str | None) -> Any:
        if kid is None:
            return next(iter(self._keys.values())) if len(self._keys) == 1 else None
        return self._keys.get(kid)

    async def _refresh(self) -> None:
        now = self._clock()
        if self._fetched_at is not None and now - self._fetched_at < _JWKS_MIN_REFETCH_S:
            return  # don't let unknown kids turn us into a JWKS hammer
        try:
            response = await self._http.get(self._url)
            response.raise_for_status()
            jwk_set = jwt.PyJWKSet.from_dict(response.json())
        except (httpx.HTTPError, ValueError, jwt.PyJWTError) as exc:
            logger.warning("JWKS fetch failed", extra={"error": type(exc).__name__})
            self._fetched_at = now if self._keys else None
            return
        self._keys = {k.key_id: k.key for k in jwk_set.keys if k.key_id}
        if not self._keys and len(jwk_set.keys) == 1:
            self._keys = {"": jwk_set.keys[0].key}
        self._fetched_at = now


class Authenticator:
    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient,
        jwks_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.mode = settings.auth_mode
        self._trusted = _parse_networks(settings.auth_trusted_proxies)
        self._issuer = settings.auth_jwt_issuer
        self._audience = settings.auth_jwt_audience
        secret = settings.auth_dev_secret
        self._dev_secret = secret.get_secret_value() if secret else secrets.token_urlsafe(48)
        self._jwks = (
            JwksKeys(settings.auth_jwks_url, http, clock=jwks_clock)
            if self.mode == "jwt" and settings.auth_jwks_url
            else None
        )

    # -- public ------------------------------------------------------------------------

    async def authenticate(self, request: Request) -> Principal:
        match self.mode:
            case "dev":
                return self._verify_dev(_bearer(request))
            case "jwt":
                return await self._verify_jwt(_bearer(request))
            case "tailscale":
                return self._tailscale(request)
            case _:
                return Principal(self.client_ip(request) or "unknown", "ip")

    def mint_dev_token(self, sub: str) -> str:
        now = int(time.time())
        return jwt.encode(
            {
                "sub": sub,
                "iss": DEV_ISSUER,
                "aud": DEV_AUDIENCE,
                "iat": now,
                "exp": now + DEV_TOKEN_TTL_S,
            },
            self._dev_secret,
            algorithm="HS256",
        )

    def client_ip(self, request: Request) -> str | None:
        """Peer IP; `X-Forwarded-For` is honoured only when the peer is a trusted proxy.
        Walks the header right to left and returns the first hop that is not itself a
        trusted proxy, so a client cannot forge the answer by prepending entries."""
        peer = request.client.host if request.client else None
        if not self._is_trusted(peer):
            return peer
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        for hop in reversed([h for h in hops if h]):
            if _ip(hop) is None:
                return peer  # malformed: don't trust any of it
            if not self._is_trusted(hop):
                return hop
        return peer

    # -- modes -------------------------------------------------------------------------

    def _verify_dev(self, token: str) -> Principal:
        try:
            claims = jwt.decode(
                token,
                self._dev_secret,
                algorithms=["HS256"],
                issuer=DEV_ISSUER,
                audience=DEV_AUDIENCE,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise Unauthorized(_describe(exc)) from None
        return Principal(str(claims["sub"]), "dev")

    async def _verify_jwt(self, token: str) -> Principal:
        assert self._jwks is not None
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in ASYMMETRIC_ALGORITHMS:
                raise Unauthorized("Unsupported token algorithm.")
            key = await self._jwks.key_for(header.get("kid"))
            claims = jwt.decode(
                token,
                key,
                algorithms=ASYMMETRIC_ALGORITHMS,
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise Unauthorized(_describe(exc)) from None
        return Principal(str(claims["sub"]), "jwt")

    def _tailscale(self, request: Request) -> Principal:
        peer = request.client.host if request.client else None
        if not self._is_trusted(peer):
            raise Unauthorized("Request did not come from a trusted proxy.")
        login = request.headers.get("tailscale-user-login", "").strip()
        if not login:
            raise Unauthorized("Missing Tailscale identity.")
        return Principal(login, "tailscale")

    def _is_trusted(self, host: str | None) -> bool:
        address = _ip(host)
        return address is not None and any(address in net for net in self._trusted)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized("Missing bearer token.")
    return token.strip()


def _describe(exc: jwt.PyJWTError) -> str:
    if isinstance(exc, jwt.ExpiredSignatureError):
        return "Token expired."
    if isinstance(exc, jwt.InvalidAudienceError | jwt.InvalidIssuerError):
        return "Token audience or issuer not accepted."
    return "Invalid token."
