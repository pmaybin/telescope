"""Request-scoped context shared by logging and the middleware."""

from contextvars import ContextVar

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
