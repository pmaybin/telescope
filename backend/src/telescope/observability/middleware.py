"""Pure-ASGI request-id + access-log middleware."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from telescope.observability.context import request_id

logger = logging.getLogger(__name__)

HEADER = "X-Request-ID"
_VALID_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def _resolve_request_id(scope: Scope) -> str:
    for name, value in scope["headers"]:
        if name == b"x-request-id":
            candidate: str = value.decode("latin-1")
            if _VALID_ID.fullmatch(candidate):
                return candidate
            break
    return uuid.uuid4().hex


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        rid = _resolve_request_id(scope)
        token = request_id.set(rid)
        start = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message["headers"] = [
                    *(h for h in message.get("headers", []) if h[0].lower() != b"x-request-id"),
                    (HEADER.lower().encode(), rid.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path: str = scope["path"]
            route = getattr(scope.get("route"), "path", None)
            client = scope.get("client")
            logger.log(
                logging.DEBUG if path == "/healthz" else logging.INFO,
                "http.request",
                extra={
                    "method": scope["method"],
                    "path": path,
                    "route": route,
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "client": client[0] if client else None,
                },
            )
            request_id.reset(token)
