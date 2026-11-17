from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from telescope.api.routes import router
from telescope.observability.logging import configure_logging
from telescope.observability.middleware import RequestIdMiddleware
from telescope.observability.otel import configure_otel, shutdown_otel
from telescope.settings import Settings

PROBLEM_JSON = "application/problem+json"


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


def create_app() -> FastAPI:
    settings = Settings()
    token = settings.github_token.get_secret_value() if settings.github_token else None
    configure_logging(settings.log_level, token=token)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        shutdown_otel()

    app = FastAPI(title="Telescope API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.openapi = lambda: _problem_json_openapi(app)  # type: ignore[method-assign]
    configure_otel(app, settings)
    return app


app = create_app()
