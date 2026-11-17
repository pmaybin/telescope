from typing import Any

from fastapi import FastAPI

from telescope.api.routes import router

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
    app = FastAPI(title="Telescope API", version="0.1.0")
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.openapi = lambda: _problem_json_openapi(app)  # type: ignore[method-assign]
    return app


app = create_app()
