from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

_correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def set_correlation_id(correlation_id: str | None = None) -> str:
    value = correlation_id or str(uuid4())
    _correlation_id_ctx.set(value)
    return value


def get_correlation_id() -> str | None:
    return _correlation_id_ctx.get()
