from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from telescope.api.deps import Now, Sleep, build_services, install_services
from telescope.api.problems import PROBLEM_JSON, UnhandledErrorMiddleware, install_problem_handlers
from telescope.api.routes import router
from telescope.observability.logging import configure_logging
from telescope.observability.middleware import RequestIdMiddleware
from telescope.observability.otel import configure_otel, shutdown_otel
from telescope.settings import Settings


def _problem_json_openapi(app: FastAPI) -> dict[str, Any]:
    """Advertise error responses as `application/problem+json` (RFC 9457) rather than
    FastAPI's default `application/json`, so generated clients type them correctly."""
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    for path in schema.get("paths", {}).values():
        for op in path.values():
            for status, resp in op.get("responses", {}).items():
                content = resp.get("content", {})
                if status.startswith(("4", "5")) and "application/json" in content:
                    content[PROBLEM_JSON] = content.pop("application/json")
    app.openapi_schema = schema
    return schema


EXPOSED_HEADERS = [
    "X-Request-ID",
    "ETag",
    "Retry-After",
    "X-GitHub-RateLimit-Limit",
    "X-GitHub-RateLimit-Remaining",
    "X-GitHub-RateLimit-Reset",
]


def create_app(
    settings: Settings | None = None,
    *,
    sleep: Sleep | None = None,
    now: Now | None = None,
) -> FastAPI:
    settings = settings or Settings()
    token = settings.github_token.get_secret_value() if settings.github_token else None
    configure_logging(settings.log_level, token=token)
    # Built eagerly (not in lifespan): ASGITransport-based tests never run lifespan.
    services = build_services(settings, sleep=sleep, now=now)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        services.snapshots.prewarm(settings.prewarm_orgs)
        try:
            yield
        finally:
            await services.aclose()
            shutdown_otel()

    app = FastAPI(title="Telescope API", version="0.1.0", lifespan=lifespan)
    install_services(app, services)
    install_problem_handlers(app)
    # Middleware order: the last added is outermost.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET"],
        expose_headers=EXPOSED_HEADERS,
    )
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.openapi = lambda: _problem_json_openapi(app)  # type: ignore[method-assign]
    configure_otel(app, settings)
    return app


app = create_app()
