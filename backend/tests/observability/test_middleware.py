import io
import json
import logging
import re
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI

from telescope.observability.logging import build_handler
from telescope.observability.middleware import RequestIdMiddleware


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    s = io.StringIO()
    lg = logging.getLogger("telescope.observability.middleware")
    lg.handlers[:] = [build_handler(None, s)]
    lg.propagate = False
    lg.setLevel(logging.INFO)
    yield s
    lg.handlers.clear()
    lg.setLevel(logging.NOTSET)
    lg.propagate = True


def _client() -> httpx.AsyncClient:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        logging.getLogger("telescope.observability.middleware").info("inside")
        return {"id": item_id}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {}

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_generates_and_echoes_request_id(stream: io.StringIO) -> None:
    async with _client() as c:
        r = await c.get("/items/1")
    rid = r.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", rid)
    recs = [json.loads(x) for x in stream.getvalue().splitlines()]
    assert recs[0]["message"] == "inside"
    assert recs[0]["request_id"] == rid
    access = recs[-1]
    assert access["message"] == "http.request"
    assert access["request_id"] == rid
    assert access["method"] == "GET"
    assert access["path"] == "/items/1"
    assert access["route"] == "/items/{item_id}"
    assert access["status_code"] == 200
    assert access["duration_ms"] >= 0
    assert "client" in access


async def test_valid_incoming_id_propagated(stream: io.StringIO) -> None:
    async with _client() as c:
        r = await c.get("/items/1", headers={"X-Request-ID": "abc.DEF_-123"})
    assert r.headers["x-request-id"] == "abc.DEF_-123"


@pytest.mark.parametrize("bad", ["has space", "a" * 129, "semi;colon", "über"])
async def test_invalid_incoming_id_replaced(stream: io.StringIO, bad: str) -> None:
    async with _client() as c:
        r = await c.get("/items/1", headers={"X-Request-ID": bad.encode("latin-1")})
    assert re.fullmatch(r"[0-9a-f]{32}", r.headers["x-request-id"])


async def test_healthz_logged_at_debug(stream: io.StringIO) -> None:
    async with _client() as c:
        await c.get("/healthz")
    assert stream.getvalue() == ""
