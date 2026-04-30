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


import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

def init_sentry() -> bool:
    if not settings.SENTRY_DSN:
        logger.info("Sentry disabled: SENTRY_DSN not configured")
        return False
    try:
        import sentry_sdk
        sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE)
        logger.info("Sentry initialized")
        return True
    except Exception:
        logger.exception("Failed to initialize Sentry")
        return False
