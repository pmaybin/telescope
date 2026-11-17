import io
import json
import logging
from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace import TracerProvider

from telescope.observability.logging import REDACTED, build_handler, configure_logging

TOKEN = "ghp_supersecret123"


@pytest.fixture
def lines() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    logger = logging.getLogger("test.obs.logging")
    logger.handlers[:] = [build_handler(TOKEN, stream)]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    yield stream
    logger.handlers.clear()


def _records(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_json_fields_and_extras(lines: io.StringIO) -> None:
    logging.getLogger("test.obs.logging").info("hello %s", "w", extra={"foo": 1})
    (rec,) = _records(lines)
    assert rec["message"] == "hello w"
    assert rec["level"] == "INFO"
    assert rec["logger"] == "test.obs.logging"
    assert str(rec["timestamp"]).endswith("Z")
    assert rec["foo"] == 1
    assert rec["trace_id"] is None
    assert "request_id" in rec


def test_trace_ids_inside_active_span(lines: io.StringIO) -> None:
    tracer = TracerProvider().get_tracer("t")
    with tracer.start_as_current_span("s") as span:
        logging.getLogger("test.obs.logging").info("in span")
        ctx = span.get_span_context()
    (rec,) = _records(lines)
    assert rec["trace_id"] == format(ctx.trace_id, "032x")
    assert rec["span_id"] == format(ctx.span_id, "016x")


def test_token_never_appears(lines: io.StringIO) -> None:
    log = logging.getLogger("test.obs.logging")
    log.info("token is %s", TOKEN)
    log.info("extra", extra={"tok": TOKEN, "nested": {"a": [f"x {TOKEN}"]}})
    log.info("hdrs", extra={"headers": {"Authorization": f"Bearer {TOKEN}", "Accept": "json"}})
    log.info("Authorization: Bearer abc.def-123 sent")
    log.info("raw bearer xyz789 here")
    out = lines.getvalue()
    assert TOKEN not in out
    assert "abc.def-123" not in out
    assert "xyz789" not in out
    assert REDACTED in out
    recs = _records(lines)
    assert recs[2]["headers"] == {"Authorization": REDACTED, "Accept": "json"}


def test_exception_text_redacted(lines: io.StringIO) -> None:
    try:
        raise ValueError(TOKEN)
    except ValueError:
        logging.getLogger("test.obs.logging").exception("boom")
    assert TOKEN not in lines.getvalue()


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        stream = io.StringIO()
        configure_logging("INFO", token=None, stream=stream)
        configure_logging("INFO", token=None, stream=stream)
        ours = [h for h in root.handlers if h not in before]
        assert len(ours) == 1
        assert logging.getLogger("uvicorn.access").disabled
        logging.getLogger("x").info("once")
        assert len(stream.getvalue().splitlines()) == 1
    finally:
        root.handlers[:] = before
