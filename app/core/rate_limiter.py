"""
TitanCode Technologies — Rate Limiting Configuration
======================================================
This module configures API rate limiting using SlowAPI to protect
against abuse, brute-force attacks, and accidental DDoS from clients.

Rate Limiting Strategy:
    ┌──────────────────────────┬─────────────────┬─────────────────────────┐
    │ Endpoint Category        │ Limit           │ Reasoning               │
    ├──────────────────────────┼─────────────────┼─────────────────────────┤
    │ Auth (login/register)    │ 5/minute        │ Prevent brute-force     │
    │ File uploads             │ 10/minute       │ Prevent storage abuse   │
    │ General API              │ 60/minute       │ Normal usage headroom   │
    └──────────────────────────┴─────────────────┴─────────────────────────┘

How SlowAPI Works:
    1. Each request is identified by the client's IP address.
    2. SlowAPI tracks how many requests each IP has made in a time window.
    3. If the limit is exceeded, the API returns 429 Too Many Requests.
    4. The response includes a `Retry-After` header telling the client
       when to try again.

Usage:
    # In an endpoint, apply a specific rate limit:
    from app.core.rate_limiter import limiter

    @router.post("/login")
    @limiter.limit("5/minute")
    async def login(request: Request, ...):
        ...

    # Or use the default limit (applied globally in main.py):
    # No decorator needed — all endpoints get 60/minute by default.
"""

import logging

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from starlette.requests import Request
from starlette.responses import JSONResponse

# Logger for rate limit events
logger = logging.getLogger(__name__)


def _custom_key_func(request: Request) -> str:
    """
    Extract the client's IP address for rate limiting.

    In production behind a reverse proxy (Nginx, Cloudflare), you should
    read from X-Forwarded-For header instead. SlowAPI's default
    `get_remote_address` handles this if configured correctly.

    Args:
        request: The incoming Starlette/FastAPI request.

    Returns:
        The client's IP address string (e.g. "192.168.1.100").
    """
    return get_remote_address(request)


# ── Create the Limiter Instance ────────────────────────────────────────
# default_limits: Applied to ALL endpoints that don't have their own
#                 @limiter.limit() decorator.
# key_func:      How to identify unique clients (by IP address).
# enabled:       Can be disabled for testing via environment variable.
#                Set RATE_LIMIT_ENABLED=false in test conftest to disable.
import os

_rate_limit_enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() != "false"

limiter = Limiter(
    key_func=_custom_key_func,
    default_limits=["60/minute"],  # General API: 60 requests per minute
    enabled=_rate_limit_enabled,
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom error handler for when a client exceeds the rate limit.

    Instead of SlowAPI's default plain-text response, we return a
    structured JSON error that matches our API's error format.

    Args:
        request: The request that triggered the rate limit.
        exc:     The RateLimitExceeded exception with details.

    Returns:
        A 429 JSON response with retry information.
    """
    logger.warning(
        f"Rate limit exceeded: {request.client.host} on {request.method} {request.url.path}"
    )
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please slow down.",
            "retry_after": str(exc.detail),
        },
    )
