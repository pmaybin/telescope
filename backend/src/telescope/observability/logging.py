"""JSON logging to stdout with trace/request correlation and secret redaction."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import IO, Any

from opentelemetry import trace
from pythonjsonlogger.json import JsonFormatter

from telescope.observability.context import request_id

REDACTED = "[REDACTED]"
_HANDLER_MARK = "_telescope_handler"

_AUTH_HEADER = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*['\"]?)(?:(?:bearer|token|basic)\s+)?[^\s'\",}]+"
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]+")
_SENSITIVE_KEYS = {"authorization", "proxy-authorization"}
_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class RedactionFilter(logging.Filter):
    """Replaces the token and Authorization/Bearer values in message, args and extras."""

    def __init__(self, token: str | None = None) -> None:
        super().__init__()
        self._token = token or None

    def _scrub_str(self, value: str) -> str:
        if self._token:
            value = value.replace(self._token, REDACTED)
        value = _AUTH_HEADER.sub(lambda m: m.group(1) + REDACTED, value)
        return _BEARER.sub(lambda m: m.group(1) + REDACTED, value)

    def scrub(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._scrub_str(value)
        if isinstance(value, Mapping):
            return {
                k: REDACTED
                if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS
                else self.scrub(v)
                for k, v in value.items()
            }
        if isinstance(value, list | tuple | set | frozenset):
            return type(value)(self.scrub(v) for v in value)
        if value is None or isinstance(value, bool | int | float):
            return value
        # Arbitrary objects (e.g. SecretStr, exceptions): scrub their string form only if needed.
        text = str(value)
        scrubbed = self._scrub_str(text)
        return scrubbed if scrubbed != text else value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.scrub(record.msg) if isinstance(record.msg, str) else record.msg
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = self.scrub(record.args)
            else:
                record.args = tuple(self.scrub(a) for a in record.args)
        for key in set(record.__dict__) - _STANDARD_ATTRS:
            record.__dict__[key] = self.scrub(record.__dict__[key])
        if record.exc_info and self._token:
            # Exception text is rendered later; pre-render it scrubbed.
            record.exc_text = self._scrub_str(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class ContextFilter(logging.Filter):
    """Adds request_id, trace_id and span_id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = trace.get_current_span().get_span_context()
        record.request_id = request_id.get()
        record.trace_id = format(ctx.trace_id, "032x") if ctx.is_valid else None
        record.span_id = format(ctx.span_id, "016x") if ctx.is_valid else None
        return True


class _Formatter(JsonFormatter):
    def add_fields(
        self,
        log_data: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_data, record, message_dict)
        ts = datetime.fromtimestamp(record.created, UTC)
        ordered = {
            "timestamp": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "trace_id": getattr(record, "trace_id", None),
            "span_id": getattr(record, "span_id", None),
        }
        rest = {k: v for k, v in log_data.items() if k not in ordered and k != "taskName"}
        log_data.clear()
        log_data.update(ordered)
        log_data.update(rest)


def build_handler(token: str | None = None, stream: IO[str] | None = None) -> logging.Handler:
    """A JSON stdout handler with context + redaction filters (stream is injectable for tests)."""
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.addFilter(ContextFilter())
    handler.addFilter(RedactionFilter(token))
    handler.setFormatter(_Formatter("%(message)s"))
    setattr(handler, _HANDLER_MARK, True)
    return handler


def configure_logging(level: str, *, token: str | None, stream: IO[str] | None = None) -> None:
    """Install JSON logging on the root logger. Idempotent."""
    root = logging.getLogger()
    for h in [h for h in root.handlers if getattr(h, _HANDLER_MARK, False)]:
        root.removeHandler(h)
    root.addHandler(build_handler(token, stream))
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
