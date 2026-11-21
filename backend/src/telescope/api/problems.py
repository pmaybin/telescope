"""RFC 9457 `application/problem+json` error responses."""

from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from telescope.errors import (
    ClientRejection,
    OrgNotFound,
    TelescopeError,
    Unauthorized,
    UpstreamBudgetExceeded,
    UpstreamError,
    UpstreamRateLimited,
)
from telescope.observability import metrics
from telescope.observability.context import request_id

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"
TYPE_BASE = "https://telescope.local/problems/"


def problem_response(
    request_path: str,
    *,
    slug: str,
    title: str,
    status: int,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": TYPE_BASE + slug,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request_path,
        "request_id": request_id.get(),
        **extensions,
    }
    return JSONResponse(
        jsonable_encoder(body), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


async def telescope_error_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, TelescopeError)
    extensions: dict[str, Any] = {}
    headers: dict[str, str] | None = None
    if isinstance(exc, OrgNotFound):
        extensions["org"] = exc.org
    if isinstance(exc, UpstreamRateLimited):
        headers = {"Retry-After": str(exc.retry_after)}
        extensions["retry_after"] = exc.retry_after
        if exc.rate_limit is not None:
            extensions["rate_limit"] = exc.rate_limit.to_info().model_dump(mode="json")
        if exc.pages_needed is not None:
            extensions["pages_needed"] = exc.pages_needed
    if isinstance(exc, Unauthorized):
        headers = {"WWW-Authenticate": "Bearer"}
    if isinstance(exc, ClientRejection):
        metrics.client_rejection(exc.reason)
        if exc.retry_after is not None:
            headers = {"Retry-After": str(exc.retry_after)}
            extensions["retry_after"] = exc.retry_after
        if isinstance(exc, UpstreamBudgetExceeded) and exc.pages_needed is not None:
            extensions["pages_needed"] = exc.pages_needed
        principal = request.scope.get("telescope.principal")
        logger.warning(
            "request rejected",
            extra={
                "reason": exc.reason,
                "slug": exc.slug,
                "status": exc.status,
                "principal": principal.key if principal else None,
                "org": request.path_params.get("org"),
            },
        )
    if isinstance(exc, UpstreamError | OrgNotFound):
        logger.warning(
            "upstream request failed",
            extra={
                "org": request.path_params.get("org"),
                "slug": exc.slug,
                "status": exc.status,
            },
        )
    return problem_response(
        request.url.path,
        slug=exc.slug,
        title=exc.title,
        status=exc.status,
        detail=exc.detail,
        headers=headers,
        **extensions,
    )


async def validation_error_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": list(e["loc"]), "msg": str(e["msg"]), "type": str(e["type"])} for e in exc.errors()
    ]
    return problem_response(
        request.url.path,
        slug="validation-error",
        title="Invalid request parameters",
        status=422,
        detail=f"{len(errors)} parameter(s) failed validation.",
        errors=errors,
    )


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    slug = {404: "not-found", 405: "method-not-allowed"}.get(exc.status_code, "http-error")
    try:
        title = HTTPStatus(exc.status_code).phrase
    except ValueError:
        title = "HTTP error"
    return problem_response(
        request.url.path,
        slug=slug,
        title=title,
        status=exc.status_code,
        detail=str(exc.detail),
        headers=dict(exc.headers) if exc.headers else None,
    )


class UnhandledErrorMiddleware:
    """Turns any unhandled exception into a 500 problem. Sits *inside* the request-id
    middleware so the response carries `X-Request-ID` and the problem its `request_id`
    (Starlette's own 500 handler runs outside every user middleware)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("unhandled exception", extra={"path": scope["path"]})
            if started:
                raise
            response = problem_response(
                scope["path"],
                slug="internal-error",
                title="Internal error",
                status=500,
                detail="An unexpected error occurred.",
            )
            await response(scope, receive, send)


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TelescopeError, telescope_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
